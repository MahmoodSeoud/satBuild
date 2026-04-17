/**
 * history.c - Deployment history database (read + write)
 *
 * Both satdeploy (Python CLI, SSH deploys) and satdeploy-apm (C, CSP deploys)
 * write to the same ~/.satdeploy/history.db. WAL mode + busy_timeout ensure
 * concurrent writers don't block each other.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/stat.h>
#include <sqlite3.h>

#include "history.h"

static int get_history_db_path(char *path_out, size_t path_size)
{
    const char *home = getenv("HOME");
    if (!home) {
        return -1;
    }

    int ret = snprintf(path_out, path_size, "%s/.satdeploy/history.db", home);
    if (ret < 0 || (size_t)ret >= path_size) {
        return -1;
    }

    return 0;
}

/* ------------------------------------------------------------------ */
/*  Read path (unchanged)                                              */
/* ------------------------------------------------------------------ */

int satdeploy_history_get_last(const char *app_name, satdeploy_deploy_record_t *record)
{
    memset(record, 0, sizeof(*record));

    char db_path[256];
    if (get_history_db_path(db_path, sizeof(db_path)) < 0) {
        return -1;
    }

    sqlite3 *db = NULL;
    if (sqlite3_open_v2(db_path, &db, SQLITE_OPEN_READONLY, NULL) != SQLITE_OK) {
        return -1;
    }

    /* Enable WAL + busy timeout even for reads (WAL readers don't block writers) */
    sqlite3_exec(db, "PRAGMA journal_mode=WAL", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA busy_timeout=5000", NULL, NULL, NULL);

    const char *sql =
        "SELECT app, file_hash, git_hash, remote_path, success "
        "FROM deployments "
        "WHERE app = ? AND success = 1 "
        "ORDER BY timestamp DESC LIMIT 1";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        sqlite3_close(db);
        return -1;
    }

    sqlite3_bind_text(stmt, 1, app_name, -1, SQLITE_STATIC);

    if (sqlite3_step(stmt) == SQLITE_ROW) {
        const char *app = (const char *)sqlite3_column_text(stmt, 0);
        const char *file_hash = (const char *)sqlite3_column_text(stmt, 1);
        const char *git_hash = (const char *)sqlite3_column_text(stmt, 2);
        const char *remote_path = (const char *)sqlite3_column_text(stmt, 3);

        if (app)
            strncpy(record->app, app, sizeof(record->app) - 1);
        if (file_hash)
            strncpy(record->file_hash, file_hash, sizeof(record->file_hash) - 1);
        if (git_hash)
            strncpy(record->git_hash, git_hash, sizeof(record->git_hash) - 1);
        if (remote_path)
            strncpy(record->remote_path, remote_path, sizeof(record->remote_path) - 1);
        record->success = sqlite3_column_int(stmt, 4);
        record->valid = 1;
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);
    return 0;
}

/* ------------------------------------------------------------------ */
/*  Write path                                                         */
/* ------------------------------------------------------------------ */

/* Full schema matching Python's history.py, plus the `transport` column */
static const char *CREATE_TABLE_SQL =
    "CREATE TABLE IF NOT EXISTS deployments ("
    "    id INTEGER PRIMARY KEY,"
    "    module TEXT NOT NULL DEFAULT 'default',"
    "    app TEXT NOT NULL,"
    "    timestamp TEXT NOT NULL,"
    "    git_hash TEXT,"
    "    file_hash TEXT NOT NULL,"
    "    remote_path TEXT NOT NULL,"
    "    backup_path TEXT,"
    "    action TEXT NOT NULL,"
    "    success INTEGER NOT NULL,"
    "    error_message TEXT,"
    "    service_hash TEXT,"
    "    vmem_cleared INTEGER NOT NULL DEFAULT 0,"
    "    provenance_source TEXT,"
    "    transport TEXT"
    ")";

/**
 * Migrate an existing database: add any columns that are missing.
 * Matches Python's History._migrate() plus the new `transport` column.
 */
static void migrate_schema(sqlite3 *db)
{
    /* SQLite's ALTER TABLE ADD COLUMN is a no-op if the column exists?
     * No — it returns an error. So we check PRAGMA table_info first. */
    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, "PRAGMA table_info(deployments)", -1, &stmt, NULL) != SQLITE_OK) {
        return;
    }

    /* Collect existing column names */
    int has_module = 0, has_service_hash = 0, has_vmem_cleared = 0;
    int has_git_hash = 0, has_provenance_source = 0, has_transport = 0;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char *col = (const char *)sqlite3_column_text(stmt, 1);
        if (!col) continue;
        if (strcmp(col, "module") == 0)            has_module = 1;
        if (strcmp(col, "service_hash") == 0)      has_service_hash = 1;
        if (strcmp(col, "vmem_cleared") == 0)      has_vmem_cleared = 1;
        if (strcmp(col, "git_hash") == 0)           has_git_hash = 1;
        if (strcmp(col, "provenance_source") == 0)  has_provenance_source = 1;
        if (strcmp(col, "transport") == 0)          has_transport = 1;
    }
    sqlite3_finalize(stmt);

    /* Add missing columns — same order as Python's _migrate() */
    if (!has_module)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN module TEXT NOT NULL DEFAULT 'default'", NULL, NULL, NULL);
    if (!has_service_hash)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN service_hash TEXT", NULL, NULL, NULL);
    if (!has_vmem_cleared)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN vmem_cleared INTEGER NOT NULL DEFAULT 0", NULL, NULL, NULL);
    if (!has_git_hash)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN git_hash TEXT", NULL, NULL, NULL);
    if (!has_provenance_source)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN provenance_source TEXT", NULL, NULL, NULL);
    if (!has_transport)
        sqlite3_exec(db, "ALTER TABLE deployments ADD COLUMN transport TEXT", NULL, NULL, NULL);
}

/**
 * Ensure the ~/.satdeploy/ directory exists.
 */
static int ensure_db_dir(void)
{
    const char *home = getenv("HOME");
    if (!home) return -1;

    char dir[256];
    snprintf(dir, sizeof(dir), "%s/.satdeploy", home);

    struct stat st;
    if (stat(dir, &st) == 0) return 0;  /* already exists */

    return mkdir(dir, 0755);
}

/**
 * Open the database for writing. Creates it if missing, runs migration,
 * enables WAL mode and busy timeout.
 */
static sqlite3 *open_db_for_write(void)
{
    char db_path[256];
    if (get_history_db_path(db_path, sizeof(db_path)) < 0) {
        return NULL;
    }

    if (ensure_db_dir() < 0) {
        return NULL;
    }

    sqlite3 *db = NULL;
    if (sqlite3_open(db_path, &db) != SQLITE_OK) {
        fprintf(stderr, "satdeploy: cannot open history.db: %s\n", sqlite3_errmsg(db));
        sqlite3_close(db);
        return NULL;
    }

    /* WAL mode + busy timeout for concurrent access with Python CLI */
    sqlite3_exec(db, "PRAGMA journal_mode=WAL", NULL, NULL, NULL);
    sqlite3_exec(db, "PRAGMA busy_timeout=5000", NULL, NULL, NULL);

    /* Create table if it doesn't exist */
    char *err = NULL;
    if (sqlite3_exec(db, CREATE_TABLE_SQL, NULL, NULL, &err) != SQLITE_OK) {
        fprintf(stderr, "satdeploy: schema creation failed: %s\n", err ? err : "unknown");
        sqlite3_free(err);
        sqlite3_close(db);
        return NULL;
    }

    /* Migrate existing databases to add any missing columns */
    migrate_schema(db);

    return db;
}

int satdeploy_history_record(const satdeploy_history_write_t *record)
{
    if (!record || !record->app || !record->file_hash || !record->remote_path || !record->action) {
        return -1;
    }

    sqlite3 *db = open_db_for_write();
    if (!db) {
        return -1;
    }

    /* Generate ISO 8601 timestamp */
    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    char timestamp[64];
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S", tm);

    const char *sql =
        "INSERT INTO deployments "
        "(module, app, timestamp, git_hash, file_hash, remote_path, "
        " backup_path, action, success, error_message, "
        " service_hash, vmem_cleared, provenance_source, transport) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?)";

    sqlite3_stmt *stmt = NULL;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) != SQLITE_OK) {
        fprintf(stderr, "satdeploy: history INSERT prepare failed: %s\n", sqlite3_errmsg(db));
        sqlite3_close(db);
        return -1;
    }

    /* Bind parameters */
    sqlite3_bind_text(stmt, 1, record->module ? record->module : "default", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 2, record->app, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, timestamp, -1, SQLITE_TRANSIENT);

    if (record->git_hash)
        sqlite3_bind_text(stmt, 4, record->git_hash, -1, SQLITE_STATIC);
    else
        sqlite3_bind_null(stmt, 4);

    sqlite3_bind_text(stmt, 5, record->file_hash, -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 6, record->remote_path, -1, SQLITE_STATIC);

    if (record->backup_path)
        sqlite3_bind_text(stmt, 7, record->backup_path, -1, SQLITE_STATIC);
    else
        sqlite3_bind_null(stmt, 7);

    sqlite3_bind_text(stmt, 8, record->action, -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, 9, record->success);

    if (record->error_message)
        sqlite3_bind_text(stmt, 10, record->error_message, -1, SQLITE_STATIC);
    else
        sqlite3_bind_null(stmt, 10);

    sqlite3_bind_text(stmt, 11, record->transport ? record->transport : "csp", -1, SQLITE_STATIC);

    int rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rc != SQLITE_DONE) {
        fprintf(stderr, "satdeploy: history INSERT failed: %s\n",
                rc == SQLITE_BUSY ? "database locked (concurrent writer)" : "unknown error");
        return -1;
    }

    return 0;
}
