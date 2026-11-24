// Dedicated launcher for the Slack listener, so Full Disk Access can be granted to
// this one binary instead of to python3. launchd starts it; it spawns
// `/usr/bin/python3 <listener.py> run` as a child (children inherit its TCC grant),
// forwards SIGTERM/SIGINT and exits with the child's status. Built by install.sh.
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

#ifndef LISTENER_PY
#error "build with -DLISTENER_PY=\"/abs/path/listener.py\""
#endif

extern char **environ;
static pid_t child = 0;

static void forward(int sig) { if (child > 0) kill(child, sig); }

int main(void) {
    char *argv[] = {"python3", LISTENER_PY, "run", NULL};
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    if (posix_spawn(&child, "/usr/bin/python3", NULL, NULL, argv, environ) != 0) {
        perror("posix_spawn");
        return 1;
    }
    int status = 0;
    while (waitpid(child, &status, 0) < 0) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
