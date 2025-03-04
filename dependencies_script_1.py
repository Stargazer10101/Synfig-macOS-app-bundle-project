import subprocess
import sys
import os


def get_dependencies(binary_path):
    # Runs otool -L on the binary and extracts the list of dependencies.
    try:
        output = subprocess.check_output(["otool", "-L", binary_path], text=True)

    except subprocess.CalledProcessError as e:
        print(f"Error running otool: {e}")
        sys.exit(1)

    lines = output.split("\n")[
        1:
    ]  # skips the first line because it is the binary itself
    dependencies = []

    for line in lines:
        if line.strip():
            lib_path = line.split()[0]  # Extract library path
            dependencies.append(lib_path)
    return dependencies


def is_system_library(lib_path):
    # Function to check if a library is a system library
    system_dirs = ["/usr/lib", "/System/Library"]
    return any(lib_path.startswith(d) for d in system_dirs)


def filter_non_system_libs(binary_path):
    # Function to obtain a list of non-system libraries(the ones that need to be bundled)
    dependencies = get_dependencies(binary_path)
    return [lib for lib in dependencies if not is_system_library(lib)]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <binary_path>")
        sys.exit(1)

    binary_path = sys.argv[1]
    if not os.path.exists(binary_path):
        print("Error: Binary file not found.")
        sys.exit(1)

    libs_to_bundle = filter_non_system_libs(binary_path)

    print("Libraries to bundle:")
    for lib in libs_to_bundle:
        print(lib)
