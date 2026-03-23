/**
 * history.h - Read deployment history from SQLite database
 *
 * Reads ~/.satdeploy/history.db to get provenance and deployment info,
 * matching the Python CLI's history module.
 */

#ifndef SATDEPLOY_HISTORY_H
#define SATDEPLOY_HISTORY_H

#define HISTORY_MAX_HASH 16
#define HISTORY_MAX_PROV 128
#define HISTORY_MAX_PATH 256

/* Last deployment record for an app */
typedef struct {
    char app[64];
    char file_hash[HISTORY_MAX_HASH];
    char git_hash[HISTORY_MAX_PROV];      /* provenance string e.g. "main@3c940acf" */
    char remote_path[HISTORY_MAX_PATH];
    int  success;
    int  valid;                            /* 0 if no record found */
} satdeploy_deploy_record_t;

/**
 * Get the last successful deployment record for an app.
 *
 * @param app_name Application name.
 * @param record   Output record (zeroed if not found).
 * @return 0 on success, -1 on error (db not found, etc).
 */
int satdeploy_history_get_last(const char *app_name, satdeploy_deploy_record_t *record);

#endif /* SATDEPLOY_HISTORY_H */
