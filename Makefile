.PHONY: bench quick build validate list test clean

bench:
	./bench

quick:
	./bench --quick

build:
	./bench build

validate:
	./bench validate

list:
	./bench list

test:
	python3 -m unittest discover -s tests -v

clean:
	cmake -E remove_directory build
	cmake -E remove_directory adapters/bevy/target
