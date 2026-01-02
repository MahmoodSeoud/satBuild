/**
 * Deploy handler - CSP port 20 command handler
 *
 * Receives protobuf-encoded deploy commands and dispatches to
 * the appropriate handler (status, deploy, rollback, etc.)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <dirent.h>
#include <sys/stat.h>
#include <libgen.h>

#include <csp/csp.h>

#include "satdeploy_agent.h"
#include "deploy.pb-c.h"

/* Maximum number of backups to return in list */
#define MAX_BACKUP_ENTRIES 64

/* Helper: recursively create directory path */
static int mkdir_p(const char *path) {
    char tmp[MAX_PATH_LEN];
    char *p = NULL;
    size_t len;

    snprintf(tmp, sizeof(tmp), "%s", path);
    len = strlen(tmp);
    if (tmp[len - 1] == '/')
        tmp[len - 1] = 0;

    for (p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = 0;
            if (mkdir(tmp, 0755) != 0 && errno != EEXIST)
                return -1;
            *p = '/';
        }
    }
    if (mkdir(tmp, 0755) != 0 && errno != EEXIST)
        return -1;

    return 0;
}

/* Helper: ensure parent directory exists */
static int ensure_parent_dir(const char *path) {
    char *path_copy = strdup(path);
    if (!path_copy) return -1;

    char *dir = dirname(path_copy);
    int ret = mkdir_p(dir);

    free(path_copy);
    return ret;
}

/* Helper: copy file (for cross-filesystem moves) */
static int copy_file_to(const char *src, const char *dst) {
    FILE *fin = fopen(src, "rb");
    if (!fin) return -1;

    FILE *fout = fopen(dst, "wb");
    if (!fout) {
        fclose(fin);
        return -1;
    }

    uint8_t buf[8192];
    size_t n;
    int result = 0;

    while ((n = fread(buf, 1, sizeof(buf), fin)) > 0) {
        if (fwrite(buf, 1, n, fout) != n) {
            result = -1;
            break;
        }
    }

    fclose(fin);
    fclose(fout);
    return result;
}

/* Chunk size for file transfers (must fit in CSP packet with overhead) */
#define CHUNK_SIZE 1400

/* Upload session state */
typedef struct {
    int active;
    char app_name[MAX_APP_NAME_LEN];
    char remote_path[MAX_PATH_LEN];
    char temp_path[MAX_PATH_LEN];
    char expected_checksum[16];
    uint32_t expected_size;
    uint32_t received_size;
    uint32_t next_chunk;
    uint32_t total_chunks;
    FILE *temp_file;
} upload_session_t;

static upload_session_t upload_session = {0};

/* Structure to collect backups during iteration */
typedef struct {
    Satdeploy__BackupEntry **entries;
    size_t count;
    size_t capacity;
} backup_collection_t;

/* Forward declarations */
static void handle_status(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp);
static void handle_verify(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp);
static void handle_list_versions(const Satdeploy__DeployRequest *req,
                                 Satdeploy__DeployResponse *resp);
static void handle_rollback(const Satdeploy__DeployRequest *req,
                            Satdeploy__DeployResponse *resp);
static void handle_deploy(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp);
static void handle_upload_start(const Satdeploy__DeployRequest *req,
                                Satdeploy__DeployResponse *resp);
static void handle_upload_chunk(const Satdeploy__DeployRequest *req,
                                Satdeploy__DeployResponse *resp);
static void handle_upload_end(const Satdeploy__DeployRequest *req,
                              Satdeploy__DeployResponse *resp);

/* Server socket for deploy connections */
static csp_socket_t deploy_socket = {0};

/**
 * Handle a single deploy connection.
 */
static void handle_connection(csp_conn_t *conn) {
    printf("[deploy] handle_connection called\n");
    fflush(stdout);

    csp_packet_t *packet = csp_read(conn, 10000);
    if (packet == NULL) {
        printf("[deploy] No data received on connection\n");
        fflush(stdout);
        return;
    }

    printf("[deploy] Received %u bytes\n", packet->length);
    fflush(stdout);

    /* Parse protobuf request */
    Satdeploy__DeployRequest *req = satdeploy__deploy_request__unpack(
        NULL, packet->length, packet->data);

    csp_buffer_free(packet);

    if (req == NULL) {
        printf("[deploy] Failed to parse protobuf request\n");
        return;
    }

    printf("[deploy] Command: %d, App: %s\n", req->command,
           req->app_name ? req->app_name : "(null)");
    fflush(stdout);

    /* Prepare response */
    Satdeploy__DeployResponse resp = SATDEPLOY__DEPLOY_RESPONSE__INIT;

    /* Dispatch to handler */
    switch (req->command) {
        case SATDEPLOY__DEPLOY_COMMAND__CMD_STATUS:
            handle_status(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_VERIFY:
            handle_verify(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_LIST_VERSIONS:
            handle_list_versions(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_ROLLBACK:
            handle_rollback(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_DEPLOY:
            handle_deploy(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_UPLOAD_START:
            handle_upload_start(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_UPLOAD_CHUNK:
            handle_upload_chunk(req, &resp);
            break;
        case SATDEPLOY__DEPLOY_COMMAND__CMD_UPLOAD_END:
            handle_upload_end(req, &resp);
            break;
        default:
            printf("[deploy] Unknown command: %d\n", req->command);
            resp.success = 0;
            resp.error_code = SATDEPLOY__DEPLOY_ERROR__ERR_UNKNOWN_COMMAND;
            resp.error_message = "Unknown command";
            break;
    }

    satdeploy__deploy_request__free_unpacked(req, NULL);

    /* Serialize and send response */
    size_t resp_size = satdeploy__deploy_response__get_packed_size(&resp);
    csp_packet_t *resp_packet = csp_buffer_get(resp_size);

    if (resp_packet != NULL) {
        resp_packet->length = satdeploy__deploy_response__pack(&resp, resp_packet->data);
        printf("[deploy] Sending response: %zu bytes, success=%d\n",
               resp_size, resp.success);
        fflush(stdout);
        csp_send(conn, resp_packet);
        printf("[deploy] Response sent\n");
        fflush(stdout);
    } else {
        printf("[deploy] Failed to allocate response buffer\n");
        fflush(stdout);
    }
}

int deploy_handler_init(void) {
    printf("[deploy] Initializing deploy handler on port %d\n", DEPLOY_PORT);

    /* Bind socket to deploy port */
    if (csp_bind(&deploy_socket, DEPLOY_PORT) != CSP_ERR_NONE) {
        printf("[deploy] Failed to bind to port %d\n", DEPLOY_PORT);
        return -1;
    }

    if (csp_listen(&deploy_socket, 10) != CSP_ERR_NONE) {
        printf("[deploy] Failed to listen on socket\n");
        return -1;
    }

    printf("[deploy] Listening on port %d\n", DEPLOY_PORT);
    return 0;
}

void deploy_handler_loop(void) {
    while (running) {
        csp_conn_t *conn = csp_accept(&deploy_socket, 1000);
        if (conn == NULL) {
            continue;
        }

        printf("[deploy] Accepted connection\n");
        handle_connection(conn);
        csp_close(conn);
    }
}

/* --- Command Handlers --- */

static void handle_status(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp) {
    (void)req;
    printf("[deploy] STATUS command\n");

    /* Scan backup directory for deployed apps */
    static Satdeploy__AppStatusEntry *app_entries[32];
    static Satdeploy__AppStatusEntry app_storage[32];
    int app_count = 0;

    DIR *dir = opendir(BACKUP_DIR);
    if (dir) {
        struct dirent *entry;
        while ((entry = readdir(dir)) != NULL && app_count < 32) {
            if (entry->d_name[0] == '.') continue;

            /* Check if it's a directory (an app) */
            char path[MAX_PATH_LEN];
            snprintf(path, sizeof(path), "%s/%s", BACKUP_DIR, entry->d_name);
            struct stat st;
            if (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) {
                Satdeploy__AppStatusEntry *app = &app_storage[app_count];
                satdeploy__app_status_entry__init(app);
                app->app_name = strdup(entry->d_name);
                app->running = 0;  /* Would need process check */
                app->binary_hash = "";
                app->remote_path = "";
                app_entries[app_count] = app;
                app_count++;
            }
        }
        closedir(dir);
    }

    resp->success = 1;
    resp->n_apps = app_count;
    resp->apps = app_entries;

    printf("[deploy] Status: agent running, %d apps with backups\n", app_count);
}

static void handle_verify(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp) {
    printf("[deploy] VERIFY command for %s at %s\n",
           req->app_name ? req->app_name : "(null)",
           req->remote_path ? req->remote_path : "(null)");

    if (req->remote_path == NULL || strlen(req->remote_path) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No remote_path specified";
        return;
    }

    static char checksum[16];
    if (compute_file_checksum(req->remote_path, checksum, sizeof(checksum)) == 0) {
        resp->success = 1;
        resp->actual_checksum = checksum;
    } else {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "File not found or unreadable";
    }
}

/**
 * Callback for backup_list - collects entries into the collection.
 */
static void backup_collect_callback(const char *version, const char *timestamp,
                                    const char *hash, const char *path,
                                    void *user_data) {
    backup_collection_t *col = (backup_collection_t *)user_data;

    if (col->count >= col->capacity) {
        return;  /* At capacity */
    }

    /* Allocate and initialize entry */
    Satdeploy__BackupEntry *entry = malloc(sizeof(Satdeploy__BackupEntry));
    if (entry == NULL) {
        return;
    }

    satdeploy__backup_entry__init(entry);
    entry->version = strdup(version ? version : "");
    entry->timestamp = strdup(timestamp ? timestamp : "");
    entry->hash = strdup(hash ? hash : "");
    entry->path = strdup(path ? path : "");

    col->entries[col->count++] = entry;
}

/**
 * Free backup entries allocated during list.
 */
static void free_backup_entries(Satdeploy__BackupEntry **entries, size_t count) {
    for (size_t i = 0; i < count; i++) {
        if (entries[i]) {
            free(entries[i]->version);
            free(entries[i]->timestamp);
            free(entries[i]->hash);
            free(entries[i]->path);
            free(entries[i]);
        }
    }
    free(entries);
}

static void handle_list_versions(const Satdeploy__DeployRequest *req,
                                 Satdeploy__DeployResponse *resp) {
    printf("[deploy] LIST_VERSIONS command for %s\n",
           req->app_name ? req->app_name : "(null)");

    if (req->app_name == NULL || strlen(req->app_name) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No app_name specified";
        return;
    }

    /* Allocate collection for backups */
    backup_collection_t col = {
        .entries = malloc(sizeof(Satdeploy__BackupEntry *) * MAX_BACKUP_ENTRIES),
        .count = 0,
        .capacity = MAX_BACKUP_ENTRIES
    };

    if (col.entries == NULL) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_FAILED;
        resp->error_message = "Memory allocation failed";
        return;
    }

    /* List backups */
    int result = backup_list(req->app_name, backup_collect_callback, &col);

    if (result < 0) {
        free_backup_entries(col.entries, col.count);
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_FAILED;
        resp->error_message = "Failed to list backups";
        return;
    }

    printf("[deploy] Found %zu backups for %s\n", col.count, req->app_name);

    resp->success = 1;
    resp->n_backups = col.count;
    resp->backups = col.entries;

    /* Note: entries will be freed after response is serialized in deploy_callback */
}

/**
 * Callback to find a specific or most recent backup.
 */
typedef struct {
    const char *target_hash;  /* NULL means find most recent */
    char found_path[MAX_PATH_LEN];
    int found;
} rollback_search_t;

static void rollback_search_callback(const char *version, const char *timestamp,
                                     const char *hash, const char *path,
                                     void *user_data) {
    (void)version;
    (void)timestamp;
    rollback_search_t *search = (rollback_search_t *)user_data;

    if (search->target_hash != NULL) {
        /* Looking for specific hash */
        if (hash != NULL && strcmp(hash, search->target_hash) == 0) {
            strncpy(search->found_path, path, MAX_PATH_LEN - 1);
            search->found_path[MAX_PATH_LEN - 1] = '\0';
            search->found = 1;
        }
    } else {
        /* Looking for most recent - just take any (backup_list returns sorted) */
        if (!search->found && path != NULL) {
            strncpy(search->found_path, path, MAX_PATH_LEN - 1);
            search->found_path[MAX_PATH_LEN - 1] = '\0';
            search->found = 1;
        }
    }
}

static void handle_rollback(const Satdeploy__DeployRequest *req,
                            Satdeploy__DeployResponse *resp) {
    printf("[deploy] ROLLBACK command for %s, hash=%s\n",
           req->app_name ? req->app_name : "(null)",
           req->rollback_hash ? req->rollback_hash : "(latest)");

    if (req->app_name == NULL || strlen(req->app_name) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No app_name specified";
        return;
    }

    if (req->remote_path == NULL || strlen(req->remote_path) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No remote_path specified";
        return;
    }

    /* Search for backup to restore */
    rollback_search_t search = {
        .target_hash = (req->rollback_hash && strlen(req->rollback_hash) > 0)
                       ? req->rollback_hash : NULL,
        .found_path = {0},
        .found = 0
    };

    int count = backup_list(req->app_name, rollback_search_callback, &search);

    if (count < 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_FAILED;
        resp->error_message = "Failed to list backups";
        return;
    }

    if (count == 0 || !search.found) {
        resp->success = 0;
        if (search.target_hash != NULL) {
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_NOT_FOUND;
            resp->error_message = "Backup with specified hash not found";
        } else {
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_NO_BACKUPS;
            resp->error_message = "No backups available";
        }
        return;
    }

    printf("[deploy] Restoring backup: %s -> %s\n", search.found_path, req->remote_path);

    /* Restore the backup */
    if (backup_restore(search.found_path, req->remote_path) != 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_RESTORE_FAILED;
        resp->error_message = "Failed to restore backup";
        return;
    }

    /* Return the backup path that was restored */
    static char restored_path[MAX_PATH_LEN];
    strncpy(restored_path, search.found_path, sizeof(restored_path) - 1);
    restored_path[sizeof(restored_path) - 1] = '\0';

    resp->success = 1;
    resp->backup_path = restored_path;
}

static void handle_deploy(const Satdeploy__DeployRequest *req,
                          Satdeploy__DeployResponse *resp) {
    printf("[deploy] DEPLOY command for %s\n",
           req->app_name ? req->app_name : "(null)");
    printf("  remote_path: %s\n", req->remote_path ? req->remote_path : "(null)");
    printf("  dtp_server: node=%u port=%u payload=%u\n",
           req->dtp_server_node, req->dtp_server_port, req->payload_id);
    printf("  expected: size=%u checksum=%s\n",
           req->expected_size,
           req->expected_checksum ? req->expected_checksum : "(null)");

    /* Validate required fields */
    if (req->app_name == NULL || strlen(req->app_name) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No app_name specified";
        return;
    }

    if (req->remote_path == NULL || strlen(req->remote_path) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No remote_path specified";
        return;
    }

    if (req->dtp_server_node == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_DTP_DOWNLOAD_FAILED;
        resp->error_message = "No DTP server node specified";
        return;
    }

    /* Step 1: TODO - Stop app via libparam if running
       For now, we skip this step since libparam integration requires
       knowing the param_name and target node */
    printf("[deploy] Step 1: Skipping app stop (not implemented)\n");

    /* Step 2: Backup current binary if it exists */
    static char backup_path_buf[MAX_PATH_LEN];
    backup_path_buf[0] = '\0';

    if (access(req->remote_path, F_OK) == 0) {
        printf("[deploy] Step 2: Creating backup of %s\n", req->remote_path);
        if (backup_create(req->app_name, req->remote_path,
                          backup_path_buf, sizeof(backup_path_buf)) != 0) {
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_FAILED;
            resp->error_message = "Failed to backup current binary";
            return;
        }
        printf("[deploy] Backup created: %s\n", backup_path_buf);
    } else {
        printf("[deploy] Step 2: No existing binary to backup\n");
    }

    /* Step 3: Download new binary via DTP */
    printf("[deploy] Step 3: Downloading new binary via DTP\n");

    /* Download to a temp file first */
    char temp_path[MAX_PATH_LEN];
    snprintf(temp_path, sizeof(temp_path), "%s.tmp", req->remote_path);

    if (dtp_download_file(req->dtp_server_node, req->payload_id,
                          temp_path, req->expected_size) != 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_DTP_DOWNLOAD_FAILED;
        resp->error_message = "DTP download failed";
        /* TODO: Restore from backup if we had one */
        return;
    }

    /* Step 4: Verify checksum */
    if (req->expected_checksum != NULL && strlen(req->expected_checksum) > 0) {
        printf("[deploy] Step 4: Verifying checksum\n");
        static char actual_checksum[16];
        if (compute_file_checksum(temp_path, actual_checksum, sizeof(actual_checksum)) != 0) {
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHECKSUM_MISMATCH;
            resp->error_message = "Failed to compute checksum";
            unlink(temp_path);
            return;
        }

        if (strcmp(actual_checksum, req->expected_checksum) != 0) {
            printf("[deploy] Checksum mismatch: expected=%s, actual=%s\n",
                   req->expected_checksum, actual_checksum);
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHECKSUM_MISMATCH;
            resp->error_message = "Checksum mismatch";
            unlink(temp_path);
            return;
        }
        printf("[deploy] Checksum verified: %s\n", actual_checksum);
    } else {
        printf("[deploy] Step 4: Skipping checksum verification (none provided)\n");
    }

    /* Step 5: Install binary (move temp to final location) */
    printf("[deploy] Step 5: Installing binary to %s\n", req->remote_path);
    if (rename(temp_path, req->remote_path) != 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_INSTALL_FAILED;
        resp->error_message = "Failed to install binary";
        unlink(temp_path);
        return;
    }

    /* Make executable */
    chmod(req->remote_path, 0755);

    /* Step 6: TODO - Start app via libparam
       For now, we skip this step */
    printf("[deploy] Step 6: Skipping app start (not implemented)\n");

    /* Success */
    resp->success = 1;
    if (backup_path_buf[0] != '\0') {
        resp->backup_path = backup_path_buf;
    }
    printf("[deploy] Deploy complete!\n");
}

/* --- Direct Upload Handlers --- */

static void upload_session_reset(void) {
    if (upload_session.temp_file) {
        fclose(upload_session.temp_file);
        upload_session.temp_file = NULL;
    }
    if (upload_session.temp_path[0]) {
        unlink(upload_session.temp_path);
    }
    memset(&upload_session, 0, sizeof(upload_session));
}

static void handle_upload_start(const Satdeploy__DeployRequest *req,
                                Satdeploy__DeployResponse *resp) {
    printf("[deploy] UPLOAD_START for %s\n",
           req->app_name ? req->app_name : "(null)");
    printf("  remote_path: %s\n", req->remote_path ? req->remote_path : "(null)");
    printf("  expected: size=%u checksum=%s chunks=%u\n",
           req->expected_size,
           req->expected_checksum ? req->expected_checksum : "(null)",
           req->total_chunks);

    /* Abort any existing upload */
    if (upload_session.active) {
        printf("[deploy] Aborting previous upload session\n");
        upload_session_reset();
    }

    /* Validate required fields */
    if (!req->app_name || strlen(req->app_name) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No app_name specified";
        return;
    }

    if (!req->remote_path || strlen(req->remote_path) == 0) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_APP_NOT_FOUND;
        resp->error_message = "No remote_path specified";
        return;
    }

    /* Initialize upload session */
    upload_session.active = 1;
    strncpy(upload_session.app_name, req->app_name, MAX_APP_NAME_LEN - 1);
    strncpy(upload_session.remote_path, req->remote_path, MAX_PATH_LEN - 1);
    snprintf(upload_session.temp_path, MAX_PATH_LEN, "/tmp/satdeploy-%s.tmp", req->app_name);

    if (req->expected_checksum) {
        strncpy(upload_session.expected_checksum, req->expected_checksum,
                sizeof(upload_session.expected_checksum) - 1);
    }
    upload_session.expected_size = req->expected_size;
    upload_session.total_chunks = req->total_chunks;
    upload_session.received_size = 0;
    upload_session.next_chunk = 0;

    /* Open temp file for writing */
    upload_session.temp_file = fopen(upload_session.temp_path, "wb");
    if (!upload_session.temp_file) {
        printf("[deploy] Failed to open temp file: %s\n", upload_session.temp_path);
        upload_session_reset();
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_FILE_WRITE_FAILED;
        resp->error_message = "Failed to create temp file";
        return;
    }

    printf("[deploy] Upload session started, expecting %u chunks\n", req->total_chunks);
    resp->success = 1;
}

static void handle_upload_chunk(const Satdeploy__DeployRequest *req,
                                Satdeploy__DeployResponse *resp) {
    printf("[deploy] UPLOAD_CHUNK seq=%u/%u, %zu bytes\n",
           req->chunk_seq, upload_session.total_chunks,
           req->chunk_data.len);

    if (!upload_session.active) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_NO_UPLOAD_IN_PROGRESS;
        resp->error_message = "No upload in progress";
        return;
    }

    if (req->chunk_seq != upload_session.next_chunk) {
        printf("[deploy] Chunk out of order: expected %u, got %u\n",
               upload_session.next_chunk, req->chunk_seq);
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHUNK_OUT_OF_ORDER;
        resp->error_message = "Chunk out of order";
        return;
    }

    if (req->chunk_data.len == 0 || req->chunk_data.data == NULL) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_FILE_WRITE_FAILED;
        resp->error_message = "Empty chunk data";
        return;
    }

    /* Write chunk to temp file */
    size_t written = fwrite(req->chunk_data.data, 1, req->chunk_data.len,
                            upload_session.temp_file);
    if (written != req->chunk_data.len) {
        printf("[deploy] Write failed: %zu of %zu bytes\n", written, req->chunk_data.len);
        upload_session_reset();
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_FILE_WRITE_FAILED;
        resp->error_message = "Failed to write chunk";
        return;
    }

    upload_session.received_size += req->chunk_data.len;
    upload_session.next_chunk++;

    resp->success = 1;
}

static void handle_upload_end(const Satdeploy__DeployRequest *req,
                              Satdeploy__DeployResponse *resp) {
    (void)req;
    printf("[deploy] UPLOAD_END - received %u bytes\n", upload_session.received_size);

    if (!upload_session.active) {
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_NO_UPLOAD_IN_PROGRESS;
        resp->error_message = "No upload in progress";
        return;
    }

    /* Close temp file */
    fclose(upload_session.temp_file);
    upload_session.temp_file = NULL;

    /* Verify size */
    if (upload_session.expected_size > 0 &&
        upload_session.received_size != upload_session.expected_size) {
        printf("[deploy] Size mismatch: expected %u, got %u\n",
               upload_session.expected_size, upload_session.received_size);
        upload_session_reset();
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHECKSUM_MISMATCH;
        resp->error_message = "Size mismatch";
        return;
    }

    /* Verify checksum */
    if (upload_session.expected_checksum[0]) {
        static char actual_checksum[16];
        if (compute_file_checksum(upload_session.temp_path, actual_checksum,
                                  sizeof(actual_checksum)) != 0) {
            upload_session_reset();
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHECKSUM_MISMATCH;
            resp->error_message = "Failed to compute checksum";
            return;
        }

        if (strcmp(actual_checksum, upload_session.expected_checksum) != 0) {
            printf("[deploy] Checksum mismatch: expected=%s, actual=%s\n",
                   upload_session.expected_checksum, actual_checksum);
            upload_session_reset();
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_CHECKSUM_MISMATCH;
            resp->error_message = "Checksum mismatch";
            return;
        }
        printf("[deploy] Checksum verified: %s\n", actual_checksum);
    }

    /* Backup existing binary if present */
    static char backup_path_buf[MAX_PATH_LEN];
    backup_path_buf[0] = '\0';

    if (access(upload_session.remote_path, F_OK) == 0) {
        printf("[deploy] Creating backup of %s\n", upload_session.remote_path);
        if (backup_create(upload_session.app_name, upload_session.remote_path,
                          backup_path_buf, sizeof(backup_path_buf)) != 0) {
            upload_session_reset();
            resp->success = 0;
            resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_BACKUP_FAILED;
            resp->error_message = "Failed to backup current binary";
            return;
        }
        printf("[deploy] Backup created: %s\n", backup_path_buf);
    }

    /* Ensure parent directory exists */
    if (ensure_parent_dir(upload_session.remote_path) != 0) {
        printf("[deploy] Failed to create parent directory\n");
        upload_session_reset();
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_INSTALL_FAILED;
        resp->error_message = "Failed to create directory";
        return;
    }

    /* Install binary (copy temp to final location, handles cross-filesystem) */
    printf("[deploy] Installing binary to %s\n", upload_session.remote_path);
    if (copy_file_to(upload_session.temp_path, upload_session.remote_path) != 0) {
        upload_session_reset();
        resp->success = 0;
        resp->error_code = SATDEPLOY__DEPLOY_ERROR__ERR_INSTALL_FAILED;
        resp->error_message = "Failed to install binary";
        return;
    }
    unlink(upload_session.temp_path);  /* Clean up temp file */

    /* Make executable */
    chmod(upload_session.remote_path, 0755);

    /* Clear session (but don't delete files) */
    upload_session.active = 0;
    upload_session.temp_path[0] = '\0';

    /* Success */
    resp->success = 1;
    if (backup_path_buf[0]) {
        resp->backup_path = backup_path_buf;
    }
    printf("[deploy] Direct upload deploy complete!\n");
}
