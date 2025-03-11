import logging
import os
import subprocess
import shutil
import sys

# Logging
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("dependency_collection.log"),
            logging.StreamHandler()
        ]
    )

def get_dependencies(binary_path):
    #Runs otool -L on the binary and extracts the list of dependencies
    try:
        output = subprocess.check_output(["otool", "-L", binary_path], text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running otool: {e}")
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
    dependencies = get_dependencies(binary_path)
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

def is_binary_file(file_path):
    #Check if a file is a Mach-O binary or dylib.
    try:
        # Try to run file command to see if it's a Mach-O file
        result = subprocess.run(
            ["file", file_path], 
            capture_output=True, 
            text=True, 
            check=True
        )
        return "Mach-O" in result.stdout
    except:
        return False

def resolve_library_path(lib_path):
    # Find the actual path of a library, resolving symlinks and searching common locations.
    # Check if path exists directly
    if os.path.exists(lib_path):
        return os.path.realpath(lib_path)
    
    # Try to find the library in common locations
    lib_name = os.path.basename(lib_path)
    common_locations = [
        "/usr/local/lib",
        "/opt/homebrew/lib",
        "/opt/local/lib"
    ]
    
    for location in common_locations:
        possible_path = os.path.join(location, lib_name)
        if os.path.exists(possible_path):
            return os.path.realpath(possible_path)
    
    # If we can't find it, return original path
    logging.warning(f"Could not resolve library path: {lib_path}")
    return lib_path

def copy_dependency(lib_path, app_bundle_path):
    """Copy a dependency into the app bundle Frameworks directory."""
    # First, resolve the actual path
    actual_path = resolve_library_path(lib_path)
    
    if not os.path.exists(actual_path):
        logging.warning(f"Dependency not found: {lib_path}")
        return None
    
    # Determine if it's a framework or a regular dylib
    if ".framework" in actual_path:
        # Extract framework name
        framework_parts = actual_path.split(".framework/")
        framework_dir = framework_parts[0] + ".framework"
        framework_name = os.path.basename(framework_dir)
        
        # Destination path in the app bundle
        dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", framework_name + ".framework")
        
        # Copy the framework if it doesn't already exist
        if not os.path.exists(dest_dir):
            logging.info(f"Copying framework: {framework_dir} -> {dest_dir}")
            try:
                shutil.copytree(framework_dir, dest_dir, symlinks=True)
            except Exception as e:
                logging.error(f"Error copying framework: {e}")
                return None
        
        # Return path to the specific binary within the framework
        if len(framework_parts) > 1:
            return os.path.join(dest_dir, framework_parts[1])
        else:
            # Try to find the main binary
            versions_dir = os.path.join(dest_dir, "Versions")
            if os.path.exists(versions_dir):
                for version in os.listdir(versions_dir):
                    bin_path = os.path.join(versions_dir, version, framework_name)
                    if os.path.exists(bin_path):
                        return bin_path
            return dest_dir
    else:
        # For regular dylibs
        lib_name = os.path.basename(actual_path)
        dest_path = os.path.join(app_bundle_path, "Contents", "Frameworks", lib_name)
        
        # Create Frameworks directory if it doesn't exist
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        
        # Copy the library if it doesn't already exist
        if not os.path.exists(dest_path):
            logging.info(f"Copying library: {actual_path} -> {dest_path}")
            try:
                shutil.copy2(actual_path, dest_path)
                # Make sure the file is writable so we can modify it
                os.chmod(dest_path, 0o644)
            except Exception as e:
                logging.error(f"Error copying library: {e}")
                return None
        
        return dest_path

def update_library_paths(binary_path, dependencies, app_bundle_path):
    """Update the library paths in a binary to use @executable_path references."""
    for original_path in dependencies:
        if is_system_library(original_path):
            continue
        
        # Determine the new path reference
        if ".framework" in original_path:
            # Handle framework paths
            framework_parts = original_path.split(".framework/")
            framework_name = os.path.basename(framework_parts[0] + ".framework")
            
            if len(framework_parts) > 1:
                subpath = framework_parts[1]
                new_path = f"@executable_path/../Frameworks/{framework_name}.framework/{subpath}"
            else:
                new_path = f"@executable_path/../Frameworks/{framework_name}.framework/{framework_name}"
        else:
            # Handle standard dylib paths
            lib_name = os.path.basename(original_path)
            new_path = f"@executable_path/../Frameworks/{lib_name}"
        
        # Update the library reference
        logging.info(f"Updating reference in {binary_path}: {original_path} -> {new_path}")
        try:
            subprocess.run([
                "install_name_tool", 
                "-change", 
                original_path, 
                new_path, 
                binary_path
            ], check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Error updating reference: {e}")

def update_library_id(lib_path):
    """Update the ID of a library to use @executable_path reference."""
    if not os.path.exists(lib_path):
        return
    
    # Determine the appropriate ID based on the location in the app bundle
    if ".framework" in lib_path:
        # Handle framework IDs
        framework_parts = lib_path.split("Frameworks/")[1].split(".framework/")
        framework_name = framework_parts[0]
        
        if len(framework_parts) > 1:
            subpath = framework_parts[1]
            new_id = f"@executable_path/../Frameworks/{framework_name}.framework/{subpath}"
        else:
            new_id = f"@executable_path/../Frameworks/{framework_name}.framework/{framework_name}"
    else:
        # Handle standard dylib IDs
        lib_name = os.path.basename(lib_path)
        new_id = f"@executable_path/../Frameworks/{lib_name}"
    
    # Update the library ID
    logging.info(f"Updating ID of {lib_path} to {new_id}")
    try:
        subprocess.run([
            "install_name_tool", 
            "-id", 
            new_id, 
            lib_path
        ], check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Error updating library ID: {e}")

def process_binary(binary_path, app_bundle_path):
    try:
        logging.info(f"Processing {binary_path}")
        
        # Skip if not a Mach-O binary
        if not is_binary_file(binary_path):
            logging.info(f"Skipping non-binary file: {binary_path}")
            return
        
        # Get all non-system dependencies
        dependencies = filter_non_system_libs(binary_path)
        
        if not dependencies:
            logging.info(f"No non-system dependencies found for {binary_path}")
            return
        
        # Process each dependency
        for lib_path in dependencies:
            # Copy the dependency to the app bundle
            copied_path = copy_dependency(lib_path, app_bundle_path)
            
            # If we've copied the dependency successfully, process it recursively
            if copied_path and copied_path != binary_path:
                process_binary(copied_path, app_bundle_path)
        
        # Update the library references in this binary
        update_library_paths(binary_path, dependencies, app_bundle_path)
        
        # If this is a library inside the Frameworks directory, update its ID
        if "Contents/Frameworks" in binary_path:
            update_library_id(binary_path)
            
        logging.info(f"Successfully processed {binary_path}")
        
    except Exception as e:
        logging.error(f"Error processing {binary_path}: {str(e)}")
        raise

def process_app_bundle(app_bundle_path):
    """Process an entire .app bundle, fixing all dependencies."""
    setup_logging()
    
    logging.info(f"Starting to process app bundle: {app_bundle_path}")
    
    # Create Frameworks directory if it doesn't exist
    frameworks_dir = os.path.join(app_bundle_path, "Contents", "Frameworks")
    os.makedirs(frameworks_dir, exist_ok=True)
    
    # Find all binaries in the app bundle
    binaries = find_binaries(app_bundle_path)
    logging.info(f"Found {len(binaries)} binaries to process")
    
    # Process each binary
    for binary in binaries:
        process_binary(binary, app_bundle_path)
    
    logging.info(f"Finished processing app bundle: {app_bundle_path}")
    return True

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process dependencies for macOS app bundle")
    parser.add_argument("--app", required=True, help="Path to the .app bundle")
    args = parser.parse_args()
    
    if not os.path.exists(args.app):
        print(f"Error: App bundle not found at {args.app}")
        sys.exit(1)
    
    success = process_app_bundle(args.app)
    sys.exit(0 if success else 1)