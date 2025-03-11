import subprocess
import sys
import os

def get_dependencies(binary_path):
    
    #Runs otol -L on the binary and extracts the list of dependencies
    try:
        output = subprocess.check_output(["otool", "-L", binary_path], text= True)
    except subprocess.CalledProcessError as e:
        print("Error running otool: {e}")
        return []
    
    lines = output.split("\n")[1:] #skipping the first line
    dependencies = []
    
    for line in lines:
        if line.strip():
            lib_path = line.split()[0] #extracting library path
            dependencies.append(lib_path)
    return dependencies

def is_system_library(lib_path):
    # A function to check if a library is a system library
    system_dirs = ["/usr/lib", "/System/Library"]
    return any(lib_path.startswith(d) for d in system_dirs)

def filter_non_system_libs(binary_path):
    dependencies= get_dependencies(binary_path)
    return [lib for lib in dependencies if not is_system_library(lib)]

def find_binaries(app_folder):
    #Finds all executable binaries within the .app folder
    binaries = []
    for root, _, files in os.walk(app_folder):
        for file in files:
            file_path = os.path.join(root, file)
            if os.access(file_path, os.X_OK) and not os.path.isdir(file_path):
                binaries.append(file_path)
    return binaries    

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script.py <app_folder>")
        sys.exit(1)
    app_folder = sys.argv[1]
    if not os.path.exists(app_folder):
        print("Error: Application folder not found.")
        sys.exit(1)
        
    binaries = find_binaries(app_folder)
    all_libs_to_bundle = set()
    
    for binary in binaries:
        libs_to_bundle = filter_non_system_libs(binary)
        all_libs_to_bundle.update(libs_to_bundle)
        
    print("Libraries to bundle:")
    for lib in sorted(all_libs_to_bundle):
        print(lib)