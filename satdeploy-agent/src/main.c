/**
 * satdeploy-agent - Satellite-side deployment agent
 *
 * Receives deployment commands from ground via CSP and manages
 * binary deployments, backups, and rollbacks.
 */

#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <pthread.h>
#include <unistd.h>

#include <csp/csp.h>

static volatile int running = 1;

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

static void *router_task(void *param) {
    (void)param;
    while (running) {
        csp_route_work();
    }
    return NULL;
}

int main(int argc, char *argv[]) {
    (void)argc;
    (void)argv;

    printf("satdeploy-agent v0.1.0\n");

    /* Setup signal handler */
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    /* Initialize CSP */
    csp_conf.hostname = "satdeploy-agent";
    csp_conf.model = "AGENT";
    csp_conf.revision = "1";
    csp_conf.version = 2;
    csp_conf.dedup = CSP_DEDUP_OFF;
    csp_init();

    /* Start router task */
    pthread_t router_handle;
    pthread_create(&router_handle, NULL, &router_task, NULL);

    printf("Agent running. Press Ctrl+C to exit.\n");

    /* Main loop */
    while (running) {
        sleep(1);
    }

    printf("\nShutting down...\n");

    /* Wait for router to finish */
    pthread_join(router_handle, NULL);

    return 0;
}
