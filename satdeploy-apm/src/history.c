/**
 * history.c - Read deployment history from SQLite database
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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
