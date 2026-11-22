CXX ?= c++
BUILD ?= ../../build
SDL_CFLAGS := $(shell pkg-config --cflags sdl2)
SDL_LIBS := $(shell pkg-config --libs sdl2)
CXXFLAGS ?= -O2 -g

.PHONY: all
all: $(BUILD)/mforce

$(BUILD)/frontend.o: main.cpp progress.hpp mforce_board.h
	mkdir -p "$(BUILD)"
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -std=c++17 -Wall -Wextra -Wpedantic $(SDL_CFLAGS) -c main.cpp -o "$@"

$(BUILD)/mforce: $(BUILD)/frontend.o $(BUILD)/libmforce_board.so
	$(CXX) $(LDFLAGS) "$<" -L"$(BUILD)" -lmforce_board $(SDL_LIBS) -pthread -Wl,-rpath,'$$ORIGIN' -o "$@"
