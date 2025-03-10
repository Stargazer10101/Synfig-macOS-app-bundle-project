import subprocess
import sys
import os
import logging



'''
def copy_dependency(lib_path, app_bundle_path):
    #Determine if it's a framework or dylib

    if ".framework" in lib_path:
        # Extract framework name
        framework_name = os.path.basename(os.path.dirname(lib_path.split(".framework")[0] + ".framework"))
        dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", f"{framework_name}.framework")
        
        # Copy entire framework folder if it doesn't exist
        if not os.path.exists(dest_dir):
            framework_dir = lib_path.split(framework_name)[0] + framework_name + ".framework"
            shutil.copytree(framework_dir, dest_dir, symlinks= True)
    else:
        # For regular dylibs
        lib_name= os.path.basename(lib_path)
        dest_path = os.path.join(app_bundle_path, "Contents", "Frameworks", lib_name)
        
        #Create Frameworks directory if it doesn't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok= True)
        
        # COpy the library
        if not os.path.exists(dest_path):
            shutil.copy2(lib_path, dest_path)
        
    return dest_path
    '''
def is_synfig_internal_lib(lib_path):
    """Check if this is an internalSynfig library from the build."""
    return 'libsynfig' in lib_path or 'libsynfigapp' in lib_path or 'libsynfigcore' in lib_path

def resolve_library_path(lib_path):
   """Resolve symlinks and ensure we get the actual library file.""" 
   # Check if path exists
   if not os.path.exists(lib_path):
       #For build directory paths, try to find in standard locations
        if is_synfig_internal_lib(lib_path):
           #Look in the build directory relative to the script
           possible_paths = [
               os.path.join(os.path.dirname(os.getwd()), "build/lib", os.path.basename(lib_path)),
               os.path.join(os.path.dirname(os.getwd()), "_debug/build/lib", os.path.basename(lib_path))
           ]
           
           for path in possible_paths:
               if os.path.exists(path):
                   return os.path.realpath(path) # Resolve any synlinks
               
        # For homebrew libraries
        if '/opt/homebrew' in lib_path:
            lib_name= os.path.basename(lib_path)
            # Try to find in default homebrew locations
            possible_paths = [
                f"/opt/homebrew/lib{lib_name}",
                f"/usr/local/lib/{lib_name}",
                lib_path
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    return os.path.realpath(path) #Resolve any symlinks
                
    # If path exists, resolve any symlinks
   if os.path.exists(lib_path):
        return os.path.realpath(lib_path)
        
    #if we can't find it, return original and let the caller handle the error
   return lib_path

def copy_dependency(lib_path, app_bundle_path):
    # Resolve the actual path before copying
    actual_lib_path = resolve_library_path(lib_path)
    
    if not os.path.exists(actual_lib_path):
        logging.warning(f"Could not find Library: {lib_path}")
        return None
    
    #Determine if it's a framework
    if ".framework" in lib_path:
        # Extract framework name
        framework_name = os.path.basename(os.path.dirname(lib_path.split(".framework")[0] + ".framework"))
        dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", f"{framework_name}.framework")
        
        # Copy entire framework folder if it doesn't exist
        if not os.path.exists(dest_dir):
            framework_dir = lib_path.split(framework_name)[0] + framework_name + ".framework"
            shutil.copytree(framework_dir, dest_dir, symlinks= True)
        else:
            # For regular dylibs
            lib_name = os.path.basename(actual_lib_path)
            dest_path = os.path.join(app_bundle_path, "Contents", "Frameworks", lib_name)
            
            #Create Frameworks directory if it doesn't exist
            os.makedirs(os.path.dirname(dest_path), exist_ok= True)
            
            # Copy the library 
            if not os.path.exists(dest_path):
                shutil.copy2(actual_lib_path, dest_path)
                #Make sure the file is writable so we can change its ID
                os.chmod(dest_path, 0o644)
        
        return dest_path


def fix_library_paths(binary_path, app_bundle_path):
    # Get dependencies
    dependencies = get_dependencies(binary_path)
    
    for lib_path in dependencies:
        if is_system_library(lib_path):
            continue  # skip system libraries
        
        # Try to resolve the path (for logging purposes)
        resolved_path = resolve_library_path(lib_path)
        if not os.path.exists(resolved_path):
            logging.warning(f"Dependency not found: {lib_path}")
            continue
        
        #Determine new path in the bundle
        if ".framework" in lib_path:
            # Handle frameworks
            # Extract framework name
            framework_name = os.path.basename(os.path.dirname(lib_path.split(".framework")[0] + ".framework"))
            dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", f"{framework_name}.framework")
        
            # Copy entire framework folder if it doesn't exist
            if not os.path.exists(dest_dir):
                framework_dir = lib_path.split(framework_name)[0] + framework_name + ".framework"
                shutil.copytree(framework_dir, dest_dir, symlinks= True)
        else:
            lib_name = os.path.basename(lib_path)
            new_path = f"@executable_path/../Frameworks/{lib_name}"
        
        # Update the reference 
        logging.info(f"Changing {lib_path} to {new_path} in {binary_path}")
        try:
            subprocess.run([
                'install_name_tool',
                '-change',
                lib_path,
                new_path,
                binary_path,
            ], check= True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to update reference: {e}")
        
        # Update the id of the library itself if we're processing it
        if os.path.basename(binary_path) == os.path.basename(lib_path):
            try:
                subprocess.run([
                    'install_name_tool',
                    '-id',
                    new_path,
                    binary_path
                ], check= True)
            except subprocess.CalledProcessError as e:
                logging.error(f"Failed to update ID: {e}")
            
            
def process_framework(framework_path, app_bundle_path):
    #Extract framework information
    framework_dir = os.path.dirname(framework_path)
    framework_name = os.path.basename(framework_dir)
    
    # Copy the framework if not already done
    dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", framework_name)
    if not os.path.exists(dest_dir):
        shutil.copytree(framework_dir, dest_dir, symlink= True)
    
    # Process all binaries in the framework
    for root, dirs, files in os.walk(dest_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if os.path.isfile(file_path) and isbinary(file_path):
                fix_library_paths(file_path, app_bundle_path)
                
def setup_logging():
    loging.basicConfig(
        level= logging.INFO,
        format= '%(asctime)s -%(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("dependency_collection.log"),
            logging.StreamHandler()
        ]
    )     
def process_binary(binary_path, app_bundle_path):
    try:
        logging.info(f"Processing {binary_path}")
        # Your processing code
def get_dependencies(binary_path):
    
    #Run otool -L on the binary and extracts the list of dependencies
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

    except Exception as e:
        logging.error(f"Error processing {binary_path}: {str(e)}")
        raise
            
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
        
        
        
          