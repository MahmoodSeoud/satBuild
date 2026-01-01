/*
 * satdeploy APM - Slash commands for satellite binary deployment
 *
 * Provides commands to interact with satdeploy-agent running on target:
 *   satdeploy status  - Query agent status
 *   satdeploy deploy  - Deploy a binary
 *   satdeploy rollback - Rollback to previous version
 *   satdeploy list    - List available backups
 *   satdeploy verify  - Verify binary checksum
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <slash/slash.h>
#include <slash/optparse.h>
#include <csp/csp.h>
#include <apm/csh_api.h>

#include "deploy.pb-c.h"

#define SATDEPLOY_PORT 20
#define DEFAULT_TIMEOUT 10000

static int send_deploy_request(unsigned int node, Satdeploy__DeployRequest *req,
                               Satdeploy__DeployResponse **resp_out)
{
    size_t req_size = satdeploy__deploy_request__get_packed_size(req);
    uint8_t *req_buf = malloc(req_size);
    if (!req_buf) {
        printf("Failed to allocate request buffer\n");
        return -1;
    }
    satdeploy__deploy_request__pack(req, req_buf);

    /* Allocate response buffer - use a reasonable max size */
    uint8_t resp_buf[4096];

    int resp_len = csp_transaction_w_opts(CSP_PRIO_NORM, node, SATDEPLOY_PORT,
                                          DEFAULT_TIMEOUT, req_buf, req_size,
                                          resp_buf, -1,  /* -1 = unknown reply size */
                                          CSP_O_CRC32);
    free(req_buf);

    if (resp_len <= 0) {
        printf("No response from agent (timeout or error)\n");
        return -1;
    }

    *resp_out = satdeploy__deploy_response__unpack(NULL, resp_len, resp_buf);
    if (!*resp_out) {
        printf("Failed to parse response\n");
        return -1;
    }

    return 0;
}

static int satdeploy_status_cmd(struct slash *slash)
{
    unsigned int node = slash_dfl_node;

    optparse_t *parser = optparse_new("satdeploy status", NULL);
    optparse_add_help(parser);
    csh_add_node_option(parser, &node);

    int argi = optparse_parse(parser, slash->argc - 1, (const char **)slash->argv + 1);
    if (argi < 0) {
        optparse_del(parser);
        return SLASH_EINVAL;
    }
    optparse_del(parser);

    Satdeploy__DeployRequest req = SATDEPLOY__DEPLOY_REQUEST__INIT;
    req.command = SATDEPLOY__DEPLOY_COMMAND__CMD_STATUS;

    Satdeploy__DeployResponse *resp = NULL;
    if (send_deploy_request(node, &req, &resp) < 0) {
        return SLASH_EIO;
    }

    if (!resp->success) {
        printf("Error: %s\n", resp->error_message);
        satdeploy__deploy_response__free_unpacked(resp, NULL);
        return SLASH_EIO;
    }

    printf("Agent status: OK\n");
    printf("Deployed apps: %zu\n", resp->n_apps);
    for (size_t i = 0; i < resp->n_apps; i++) {
        Satdeploy__AppStatusEntry *app = resp->apps[i];
        printf("  %s: %s [%s] @ %s\n",
               app->app_name,
               app->running ? "running" : "stopped",
               app->binary_hash,
               app->remote_path);
    }

    satdeploy__deploy_response__free_unpacked(resp, NULL);
    return SLASH_SUCCESS;
}

static int satdeploy_deploy_cmd(struct slash *slash)
{
    unsigned int node = slash_dfl_node;
    unsigned int appsys_node = 0;
    unsigned int run_node = 0;
    unsigned int dtp_server_node = 0;
    unsigned int dtp_server_port = 7;
    unsigned int payload_id = 0;
    unsigned int expected_size = 0;
    char *app_name = NULL;
    char *param_name = NULL;
    char *remote_path = NULL;
    char *checksum = NULL;

    optparse_t *parser = optparse_new("satdeploy deploy", "<app_name>");
    optparse_add_help(parser);
    csh_add_node_option(parser, &node);
    optparse_add_string(parser, 'p', "param", "NAME", &param_name, "Parameter name (e.g., mng_dipp)");
    optparse_add_string(parser, 'r', "remote", "PATH", &remote_path, "Remote installation path");
    optparse_add_unsigned(parser, 'a', "appsys", "NODE", 0, &appsys_node, "App-sys-manager node");
    optparse_add_unsigned(parser, 'R', "run-node", "NODE", 0, &run_node, "Node where app runs");
    optparse_add_unsigned(parser, 'd', "dtp-node", "NODE", 0, &dtp_server_node, "DTP server node");
    optparse_add_unsigned(parser, 'P', "dtp-port", "PORT", 0, &dtp_server_port, "DTP server port");
    optparse_add_unsigned(parser, 'i', "payload-id", "ID", 0, &payload_id, "DTP payload ID");
    optparse_add_unsigned(parser, 's', "size", "BYTES", 0, &expected_size, "Expected file size");
    optparse_add_string(parser, 'c', "checksum", "HEX", &checksum, "Expected SHA256 checksum (8 chars)");

    int argi = optparse_parse(parser, slash->argc - 1, (const char **)slash->argv + 1);
    if (argi < 0) {
        optparse_del(parser);
        return SLASH_EINVAL;
    }

    if (argi >= slash->argc - 1) {
        printf("Error: app_name required\n");
        optparse_help(parser, stdout);
        optparse_del(parser);
        return SLASH_EUSAGE;
    }
    app_name = slash->argv[argi + 1];
    optparse_del(parser);

    if (!remote_path || !dtp_server_node || !payload_id || !expected_size || !checksum) {
        printf("Error: --remote, --dtp-node, --payload-id, --size, and --checksum are required\n");
        return SLASH_EUSAGE;
    }

    Satdeploy__DeployRequest req = SATDEPLOY__DEPLOY_REQUEST__INIT;
    req.command = SATDEPLOY__DEPLOY_COMMAND__CMD_DEPLOY;
    req.app_name = app_name;
    req.param_name = param_name ? param_name : "";
    req.remote_path = remote_path;
    req.appsys_node = appsys_node;
    req.run_node = run_node;
    req.dtp_server_node = dtp_server_node;
    req.dtp_server_port = dtp_server_port;
    req.payload_id = payload_id;
    req.expected_size = expected_size;
    req.expected_checksum = checksum;

    printf("Deploying %s to node %u...\n", app_name, node);

    Satdeploy__DeployResponse *resp = NULL;
    if (send_deploy_request(node, &req, &resp) < 0) {
        return SLASH_EIO;
    }

    if (!resp->success) {
        printf("Deploy failed: %s (code %u)\n", resp->error_message, resp->error_code);
        satdeploy__deploy_response__free_unpacked(resp, NULL);
        return SLASH_EIO;
    }

    printf("Deploy successful!\n");
    if (resp->backup_path && strlen(resp->backup_path) > 0) {
        printf("Backup created: %s\n", resp->backup_path);
    }

    satdeploy__deploy_response__free_unpacked(resp, NULL);
    return SLASH_SUCCESS;
}

static int satdeploy_rollback_cmd(struct slash *slash)
{
    unsigned int node = slash_dfl_node;
    char *app_name = NULL;
    char *hash = NULL;

    optparse_t *parser = optparse_new("satdeploy rollback", "<app_name>");
    optparse_add_help(parser);
    csh_add_node_option(parser, &node);
    optparse_add_string(parser, 'H', "hash", "HASH", &hash, "Specific backup hash to restore");

    int argi = optparse_parse(parser, slash->argc - 1, (const char **)slash->argv + 1);
    if (argi < 0) {
        optparse_del(parser);
        return SLASH_EINVAL;
    }

    if (argi >= slash->argc - 1) {
        printf("Error: app_name required\n");
        optparse_help(parser, stdout);
        optparse_del(parser);
        return SLASH_EUSAGE;
    }
    app_name = slash->argv[argi + 1];
    optparse_del(parser);

    Satdeploy__DeployRequest req = SATDEPLOY__DEPLOY_REQUEST__INIT;
    req.command = SATDEPLOY__DEPLOY_COMMAND__CMD_ROLLBACK;
    req.app_name = app_name;
    req.rollback_hash = hash ? hash : "";

    printf("Rolling back %s on node %u...\n", app_name, node);

    Satdeploy__DeployResponse *resp = NULL;
    if (send_deploy_request(node, &req, &resp) < 0) {
        return SLASH_EIO;
    }

    if (!resp->success) {
        printf("Rollback failed: %s (code %u)\n", resp->error_message, resp->error_code);
        satdeploy__deploy_response__free_unpacked(resp, NULL);
        return SLASH_EIO;
    }

    printf("Rollback successful!\n");
    satdeploy__deploy_response__free_unpacked(resp, NULL);
    return SLASH_SUCCESS;
}

static int satdeploy_list_cmd(struct slash *slash)
{
    unsigned int node = slash_dfl_node;
    char *app_name = NULL;

    optparse_t *parser = optparse_new("satdeploy list", "<app_name>");
    optparse_add_help(parser);
    csh_add_node_option(parser, &node);

    int argi = optparse_parse(parser, slash->argc - 1, (const char **)slash->argv + 1);
    if (argi < 0) {
        optparse_del(parser);
        return SLASH_EINVAL;
    }

    if (argi >= slash->argc - 1) {
        printf("Error: app_name required\n");
        optparse_help(parser, stdout);
        optparse_del(parser);
        return SLASH_EUSAGE;
    }
    app_name = slash->argv[argi + 1];
    optparse_del(parser);

    Satdeploy__DeployRequest req = SATDEPLOY__DEPLOY_REQUEST__INIT;
    req.command = SATDEPLOY__DEPLOY_COMMAND__CMD_LIST_VERSIONS;
    req.app_name = app_name;

    Satdeploy__DeployResponse *resp = NULL;
    if (send_deploy_request(node, &req, &resp) < 0) {
        return SLASH_EIO;
    }

    if (!resp->success) {
        printf("Error: %s\n", resp->error_message);
        satdeploy__deploy_response__free_unpacked(resp, NULL);
        return SLASH_EIO;
    }

    printf("Backups for %s: %zu\n", app_name, resp->n_backups);
    for (size_t i = 0; i < resp->n_backups; i++) {
        Satdeploy__BackupEntry *backup = resp->backups[i];
        printf("  [%zu] %s\n", i + 1, backup->version);
        printf("      Timestamp: %s\n", backup->timestamp);
        printf("      Hash: %s\n", backup->hash);
        printf("      Path: %s\n", backup->path);
    }

    if (resp->n_backups == 0) {
        printf("  (no backups found)\n");
    }

    satdeploy__deploy_response__free_unpacked(resp, NULL);
    return SLASH_SUCCESS;
}

static int satdeploy_verify_cmd(struct slash *slash)
{
    unsigned int node = slash_dfl_node;
    char *app_name = NULL;
    char *remote_path = NULL;
    char *expected_checksum = NULL;

    optparse_t *parser = optparse_new("satdeploy verify", "<app_name>");
    optparse_add_help(parser);
    csh_add_node_option(parser, &node);
    optparse_add_string(parser, 'r', "remote", "PATH", &remote_path, "Remote file path to verify");
    optparse_add_string(parser, 'c', "checksum", "HEX", &expected_checksum, "Expected checksum to compare");

    int argi = optparse_parse(parser, slash->argc - 1, (const char **)slash->argv + 1);
    if (argi < 0) {
        optparse_del(parser);
        return SLASH_EINVAL;
    }

    if (argi >= slash->argc - 1) {
        printf("Error: app_name required\n");
        optparse_help(parser, stdout);
        optparse_del(parser);
        return SLASH_EUSAGE;
    }
    app_name = slash->argv[argi + 1];
    optparse_del(parser);

    Satdeploy__DeployRequest req = SATDEPLOY__DEPLOY_REQUEST__INIT;
    req.command = SATDEPLOY__DEPLOY_COMMAND__CMD_VERIFY;
    req.app_name = app_name;
    req.remote_path = remote_path ? remote_path : "";
    req.expected_checksum = expected_checksum ? expected_checksum : "";

    Satdeploy__DeployResponse *resp = NULL;
    if (send_deploy_request(node, &req, &resp) < 0) {
        return SLASH_EIO;
    }

    if (!resp->success) {
        printf("Verify failed: %s\n", resp->error_message);
        satdeploy__deploy_response__free_unpacked(resp, NULL);
        return SLASH_EIO;
    }

    printf("Checksum: %s\n", resp->actual_checksum);
    if (expected_checksum && strlen(expected_checksum) > 0) {
        if (strncmp(resp->actual_checksum, expected_checksum, strlen(expected_checksum)) == 0) {
            printf("Verification: MATCH\n");
        } else {
            printf("Verification: MISMATCH (expected %s)\n", expected_checksum);
        }
    }

    satdeploy__deploy_response__free_unpacked(resp, NULL);
    return SLASH_SUCCESS;
}

slash_command_sub(satdeploy, status, satdeploy_status_cmd, NULL, "Query agent status and list deployed apps");
slash_command_sub(satdeploy, deploy, satdeploy_deploy_cmd, "<app> [options]", "Deploy a binary to the target");
slash_command_sub(satdeploy, rollback, satdeploy_rollback_cmd, "<app> [-H hash]", "Rollback to previous version");
slash_command_sub(satdeploy, list, satdeploy_list_cmd, "<app>", "List available backups for an app");
slash_command_sub(satdeploy, verify, satdeploy_verify_cmd, "<app> [-r path] [-c checksum]", "Verify binary checksum");
