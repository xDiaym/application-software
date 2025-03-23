#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>
#define PHILOSOPHERS_N (5)

pthread_mutex_t io_mut;
pthread_mutex_t fork_mut[PHILOSOPHERS_N];
pthread_t philosopher[PHILOSOPHERS_N];

void Log(const char* __restrict fmt, ...) {
  va_list va;
  va_start(va, fmt);
  pthread_mutex_lock(&io_mut);
  vprintf(fmt, va);
  fflush(stdout);
  pthread_mutex_unlock(&io_mut);
  va_end(va);
}

void* DoPhilosopherThings(void* arg) {
  intptr_t n = (intptr_t)arg;

  while (1) {
  think:
    Log("Philosopher #%d is thinking\n", n);
    sleep(rand() % 3);

    Log("Philosopher #%d is hungry now\n", n);
    pthread_mutex_lock(&fork_mut[n]);
    if (pthread_mutex_trylock(&fork_mut[(n + 1) % PHILOSOPHERS_N])) {
      pthread_mutex_unlock(&fork_mut[n]);
      Log("Philosopher #%d failed to capture fork #%d\n", n, (n + 1) % PHILOSOPHERS_N);
      goto think;
    }

    Log("Philosopher #%d is eating\n", n);
    sleep(rand() % 3);

    pthread_mutex_unlock(&fork_mut[(n + 1) % PHILOSOPHERS_N]);
    pthread_mutex_unlock(&fork_mut[n]);
  }

  return NULL;
}

int main(void) {
  pthread_mutex_init(&io_mut, NULL);
  for (int i = 0; i < PHILOSOPHERS_N; ++i)
    pthread_mutex_init(&fork_mut[i], NULL);

  for (int i = 0; i < PHILOSOPHERS_N; ++i)
    pthread_create(&philosopher[i], NULL, &DoPhilosopherThings, (void*)(intptr_t)i);

  void* dummy_;
  for (int i = 0; i < PHILOSOPHERS_N; ++i)
    pthread_join(philosopher[i], &dummy_);

  for (int i = 0; i < PHILOSOPHERS_N; ++i)
    pthread_mutex_destroy(&fork_mut[i]);
  pthread_mutex_destroy(&io_mut);

  return 0;
}
