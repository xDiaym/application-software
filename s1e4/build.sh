#!/bin/bash

set -xe

clang \
    -Werror -Wall -Wextra -Wpedantic \
    -lpthread \
    -fsanitize=thread \
    main.c
