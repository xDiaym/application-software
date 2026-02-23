CXXFLAGS?=-std=c++20 -O2 -march=native -ldl
CXX?=clang++

all: omp

.PHONY: omp
omp:
	$(CXX) $(CXXFLAGS) -DUSE_OPENMP=1 -fopenmp server/main.cpp -o omp

clean:
	rm out.dat omp