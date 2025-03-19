import logging
import os
import subprocess
import shutil
import sys
import argparse
import re
from glob import glob

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
    try:
        output = subprocess.check_output(["otool", "-L", binary_path], text=True)
        deps = []
        for line in output.strip().split('\n')[1:]:  # Skip first line
            match = re.match(r'^\s*(@?[^\s]+)', line)
            if match:
                deps.append(match.group(1))
        return deps
    except subprocess.CalledProcessError as e:
        logging.error(f"Error running otool: {e}")
        return []

def resolve_rpath(binary_path, rpath_lib):
    try:
        output = subprocess.check_output(["otool", "-l", binary_path], text=True)
        rpaths = []
        binary_dir = os.path.dirname(binary_path)
        app_bundle_root = os.path.join(binary_dir, "..", "..", "..")  # Added
        
        # Add default app bundle paths
        default_app_paths = [
            os.path.join(app_bundle_root, "Frameworks"),
            os.path.join(app_bundle_root, "Resources", "lib")
        ]
        
        # Existing RPATH processing
        for line in output.splitlines():
            if "path" in line and "LC_RPATH" in line:
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                rpath = parts[2]
                
                # Expand @loader_path/@executable_path
                expanded = rpath
                if "@loader_path" in rpath:
                    expanded = os.path.normpath(rpath.replace("@loader_path", binary_dir))
                elif "@executable_path" in rpath:
                    expanded = os.path.normpath(rpath.replace("@executable_path", 
                        os.path.join(binary_dir, "..", "MacOS")))
                
                rpaths.append(expanded)
        
        # Add default app paths to search locations
        rpaths += default_app_paths  # Critical addition
        
        # Search in resolved paths
        for rpath in rpaths:
            possible_path = os.path.join(rpath, rpath_lib)
            if os.path.exists(possible_path):
                return os.path.realpath(possible_path)
        
        logging.warning(f"Could not resolve @rpath reference: {rpath_lib}")
        return None
    except Exception as e:
        logging.error(f"Error resolving @rpath: {e}")
        return None

def resolve_library_path(lib_path, binary_path=None):
    try:
        # Handle @rpath references
        if lib_path.startswith("@rpath") and binary_path:
            rpath_lib = lib_path.split("@rpath/", 1)[1]
            resolved = resolve_rpath(binary_path, rpath_lib)
            if resolved:
                return resolved

        # Handle direct paths
        if os.path.exists(lib_path):
            return os.path.realpath(lib_path)

        # Search common locations with version flexibility
        lib_name_base = os.path.basename(lib_path).split('.dylib', 1)[0]
        version_pattern = re.compile(rf'^{re.escape(lib_name_base)}(\.\d+)*\.dylib$')  # Handles multi-part versions
        search_paths = [
            "/opt/homebrew/lib",  # Already present
            "/opt/homebrew/opt/*/lib",  # Add wildcard to cover all Homebrew formulae
            "/usr/local/opt/*/lib",  # Intel Homebrew
            "/usr/local/opt/sqlite/lib",
            "/opt/homebrew/opt/sqlite/lib",
            "/usr/local/lib", 
            "/opt/homebrew/lib",
            "/opt/local/lib",
            "/usr/lib", 
            "/Library/Frameworks",
            os.path.join(os.path.dirname(binary_path), "..", "lib") if binary_path else None,
            os.path.join(os.path.dirname(binary_path), "..", "Frameworks") if binary_path else None
        ]
        
        # Regex pattern for versioned libraries
        version_pattern = re.compile(rf'^{re.escape(lib_name_base)}(\.\d+)*\.dylib$')
        
        for path in filter(None, search_paths):
            # Check for exact match first
            candidate = os.path.join(path, lib_name_base + ".dylib")
            if os.path.exists(candidate):
                return os.path.realpath(candidate)
            
            # Check for versioned matches
            if os.path.exists(path):
                for f in os.listdir(path):
                    if version_pattern.match(f):
                        return os.path.realpath(os.path.join(path, f))

        logging.warning(f"Could not resolve library path: {lib_path}")
        return lib_path  # Return original path to avoid None
    except Exception as e:
        logging.error(f"Error resolving library path: {e}")
        return lib_path

def copy_dependency(lib_path, app_bundle_path, binary_path=None):
    try:
        actual_path = resolve_library_path(lib_path, binary_path)
        
        if not actual_path or not os.path.exists(actual_path):
            # Try finding versioned library in valid directories
            lib_dir = os.path.dirname(lib_path)
            lib_base = os.path.basename(lib_path).split('.dylib', 1)[0]
            version_pattern = re.compile(rf'^{re.escape(lib_base)}(\.\d+)*\.dylib$')
            
            if os.path.isdir(lib_dir):
                for f in os.listdir(lib_dir):
                    if version_pattern.match(f):
                        actual_path = os.path.join(lib_dir, f)
                        break
            
            if not actual_path or not os.path.exists(actual_path):
                logging.warning(f"Dependency not found: {lib_path}")
                return None

        # Handle frameworks with symlinks
        if ".framework" in actual_path:
            return handle_framework(actual_path, app_bundle_path)
        
        file_type = subprocess.run(
            ["file", "-b", actual_path],
            capture_output=True, text=True
        ).stdout.lower()

        if "mach-o executable" in file_type:
            dest_dir = os.path.join(app_bundle_path, "Contents", "Resources", "bin")
        elif "shared library" in file_type or ".dylib" in actual_path or ".so" in actual_path:
            dest_dir = os.path.join(app_bundle_path, "Contents", "Resources", "lib")
        else:
            logging.warning(f"Unhandled file type: {actual_path}")
            return None

        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, os.path.basename(actual_path))
        
        if not os.path.exists(dest_path):
            logging.info(f"Copying {os.path.basename(actual_path)} to {dest_dir}")
            # Resolve symlinks before copying
            if os.path.islink(actual_path):
                link_target = os.path.realpath(actual_path)
                if os.path.exists(link_target):
                    shutil.copy2(link_target, dest_path)
            else:
                shutil.copy2(actual_path, dest_path)
            
            # Set appropriate permissions
            os.chmod(dest_path, 0o755 if "executable" in file_type else 0o644)
        
        return dest_path
    except Exception as e:
        logging.error(f"Error copying dependency: {e}")
        return None

def handle_framework(actual_path, app_bundle_path):
    try:
        # Resolve framework symlinks
        resolved_path = os.path.realpath(actual_path)
        framework_dir = resolved_path.split(".framework/")[0] + ".framework"
        framework_name = os.path.basename(framework_dir)
        dest_dir = os.path.join(app_bundle_path, "Contents", "Frameworks", framework_name)
        
        if not os.path.exists(dest_dir):
            logging.info(f"Copying framework: {framework_name}")
            # Copy entire framework, resolving symlinks
            shutil.copytree(framework_dir, dest_dir, copy_function=shutil.copy2)
            
            # Fix symlinks within framework
            for root, dirs, files in os.walk(dest_dir):
                for name in files + dirs:
                    path = os.path.join(root, name)
                    if os.path.islink(path):
                        link_target = os.path.realpath(path)
                        if link_target.startswith(framework_dir):
                            relative = os.path.relpath(link_target, os.path.dirname(path))
                            os.unlink(path)
                            os.symlink(relative, path)
        
        return os.path.join(dest_dir, resolved_path.split(".framework/", 1)[1])
    except Exception as e:
        logging.error(f"Error handling framework: {e}")
        return None

def update_library_paths(binary_path, dependencies, app_bundle_path):
    for original_path in dependencies:
        if original_path.startswith(("/usr/lib", "/System/Library")):
            continue  # Skip system libraries
        
        lib_name = os.path.basename(original_path)
        actual_path = resolve_library_path(original_path, binary_path)

        if ".framework" in original_path:
            framework_parts = original_path.split(".framework/")
            framework_name = os.path.basename(framework_parts[0] + ".framework")
            new_path = f"@executable_path/../Frameworks/{framework_name}/{framework_parts[1] if len(framework_parts) > 1 else framework_name}"
        else:
            file_type = subprocess.run(
                ["file", "-b", actual_path],
                capture_output=True, text=True
            ).stdout.lower()

            if "mach-o executable" in file_type:
                new_path = f"@executable_path/../Resources/bin/{lib_name}"
            else:
                new_path = f"@executable_path/../Resources/lib/{lib_name}"

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
    if not os.path.exists(lib_path):
        return

    if "Contents/Frameworks" in lib_path:
        framework_parts = lib_path.split("Frameworks/")[1].split(".framework/")
        framework_name = framework_parts[0]
        new_id = f"@executable_path/../Frameworks/{framework_name}.framework/{framework_parts[1] if len(framework_parts) > 1 else framework_name}"
    elif "Contents/Resources/bin" in lib_path:
        lib_name = os.path.basename(lib_path)
        new_id = f"@executable_path/../Resources/bin/{lib_name}"
    elif "Contents/Resources/lib" in lib_path:
        lib_name = os.path.basename(lib_path)
        new_id = f"@executable_path/../Resources/lib/{lib_name}"
    else:
        return

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
        
        # Skip Python extensions inside framework
        if "Python.framework" in binary_path and binary_path.endswith(".so"):
            logging.info(f"Skipping Python framework C extension: {binary_path}")
            return
        
        if not is_binary_file(binary_path):
            logging.info(f"Skipping non-binary file: {binary_path}")
            return
        
        dependencies = get_dependencies(binary_path)
        dependencies = [dep for dep in dependencies if not dep.startswith(("/usr/lib", "/System/Library"))]
        
        if not dependencies:
            logging.info(f"No non-system dependencies found for {binary_path}")
            return
        
        # Process dependencies first
        for lib_path in dependencies:
            copied_path = copy_dependency(lib_path, app_bundle_path, binary_path)
            if copied_path and copied_path != binary_path:
                process_binary(copied_path, app_bundle_path)
        
        # Add RPATHs to help resolve @rpath references
        needed_rpaths = [
            "@executable_path/../Resources/lib",
            "@executable_path/../Frameworks"
        ]
        
        for rpath in needed_rpaths:
            try:
                subprocess.run([
                    "install_name_tool",
                    "-add_rpath",
                    rpath,
                    binary_path
                ], check=True)
                logging.info(f"Added RPATH {rpath} to {binary_path}")
            except subprocess.CalledProcessError as e:
                if "would duplicate path, file already has LC_RPATH" in e.output:
                    logging.debug(f"RPATH {rpath} already exists in {binary_path}")
                else:
                    logging.warning(f"Failed to add RPATH {rpath} to {binary_path}: {e}")
        
        # Update library paths in the binary
        update_library_paths(binary_path, dependencies, app_bundle_path)
        
        # Handle version symlinks for MLT and similar libraries
        if "libmlt" in binary_path:
            lib_dir = os.path.join(app_bundle_path, "Contents", "Resources", "lib")
            base_name = os.path.basename(binary_path).split(".", 1)[0]
            major_version = base_name.split("-")[-1].rsplit(".", 1)[0]  # Extract 7.7 from libmlt++-7.7.30.0.dylib
            
            # Create version symlink if needed (e.g. libmlt++-7.7.dylib -> libmlt++-7.7.30.0.dylib)
            symlink_name = f"{base_name.split('-')[0]}-{major_version}.dylib"
            symlink_path = os.path.join(lib_dir, symlink_name)
            if not os.path.exists(symlink_path):
                try:
                    os.symlink(os.path.basename(binary_path), symlink_path)
                    logging.info(f"Created version symlink: {symlink_name} -> {os.path.basename(binary_path)}")
                except Exception as e:
                    logging.error(f"Failed to create version symlink: {e}")
        
        # Update library ID if needed
        if "Contents/Frameworks" in binary_path or "Contents/Resources" in binary_path:
            update_library_id(binary_path)
            
        logging.info(f"Successfully processed {binary_path}")
        
    except Exception as e:
        logging.error(f"Error processing {binary_path}: {str(e)}")
        raise

def process_app_bundle(app_bundle_path):
    logging.info(f"Starting to process app bundle: {app_bundle_path}")
    
    # Create required directories
    for d in ["Frameworks", "Resources/bin", "Resources/lib"]:
        os.makedirs(os.path.join(app_bundle_path, "Contents", d), exist_ok=True)
    
    binaries = find_binaries(app_bundle_path)
    logging.info(f"Found {len(binaries)} binaries to process")
    
    for binary in binaries:
        process_binary(binary, app_bundle_path)
    
    logging.info(f"Finished processing app bundle: {app_bundle_path}")
    return True

def find_binaries(app_folder):
    binaries = []
    for root, _, files in os.walk(app_folder):
        for file in files:
            file_path = os.path.join(root, file)
            if os.access(file_path, os.X_OK) and not os.path.isdir(file_path):
                binaries.append(file_path)
    return binaries

def is_binary_file(file_path):
    try:
        result = subprocess.run(
            ["file", "-b", file_path], 
            capture_output=True, 
            text=True, 
            check=True
        )
        return any(x in result.stdout for x in ["Mach-O", "shared library"])
    except:
        return False

if __name__ == "__main__":
    setup_logging()
    parser = argparse.ArgumentParser(description="Process dependencies for macOS app bundle")
    parser.add_argument("--app", required=True, help="Path to the .app bundle")
    args = parser.parse_args()
    
    if not os.path.exists(args.app):
        logging.error(f"App bundle not found at {args.app}")
        sys.exit(1)
    
    try:
        process_app_bundle(args.app)
        logging.info("Dependency collection completed successfully")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
        sys.exit(1)