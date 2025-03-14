import logging
import os
import subprocess
from pathlib import Path
import sys

# Reusing the existing logging setup
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("code_signing.log"),
            logging.StreamHandler()
        ]
    )
    
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
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to check if {file_path} is a binary: {e}")
        return False


def find_signable_files(app_bundle_path):
    """Find all files that need signing (executables, libraries, frameworks)."""
    signable_files = []
    
    # Define file extensions and directories to target
    extensions = {".dylib", ".so", ".framework", ".app", ""}  # "" for executables
    skip_dirs = {"Headers", "Resources", "Python.framework"}  # Skip non-binary parts
    
    for root, dirs, files in os.walk(app_bundle_path):
        # Skip non-binary directories in frameworks
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        
        for file in files:
            file_path = os.path.join(root, file)
            
            # Check if it's a Mach-O binary (reusing the `is_binary_file` function)
            if is_binary_file(file_path):
                signable_files.append(file_path)
            
            # Special handling for framework bundles
            if file_path.endswith(".framework"):
                framework_binary = os.path.join(file_path, os.path.splitext(file)[0])
                if os.path.exists(framework_binary):
                    signable_files.append(framework_binary)
    
    return signable_files

def sign_file(file_path, signing_identity, entitlements=None):
    """Sign a single file with the specified identity."""
    cmd = [
        "codesign",
        "--force",  # Replace existing signatures
        "--timestamp",  # Add a secure timestamp
        "--options=runtime",  # Enable hardened runtime
        "-s", signing_identity
    ]
    
    if entitlements and os.path.exists(entitlements):
        cmd.extend(["--entitlements", entitlements])
    
    cmd.append(file_path)
    
    try:
        logging.info(f"Signing {file_path}")
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to sign {file_path}: {e}")
        raise

def sign_app_bundle(app_bundle_path, signing_identity, entitlements=None):
    """Sign the entire app bundle."""
    setup_logging()
    
    # Step 1: Sign all nested binaries/libraries first
    signable_files = find_signable_files(app_bundle_path)
    
    # Sort files to sign dependencies first:
    # - Libraries before executables
    # - Frameworks before apps
    signable_files.sort(
        key=lambda x: (os.path.dirname(x).count("/"), x.endswith(".app")),
        reverse=True  # Deepest files first
    )
    
    # Step 2: Sign individual files
    for file in signable_files:
        if not file.endswith(".app"):  # Save .app for last
            sign_file(file, signing_identity, entitlements)
    
    # Step 3: Sign the main app bundle
    sign_file(app_bundle_path, signing_identity, entitlements)
    
    # Step 4: Verify signatures
    verify_signature(app_bundle_path)

def verify_signature(app_bundle_path):
    """Verify all signatures in the app bundle."""
    try:
        subprocess.run(
            ["codesign", "-dv", "--strict=all", app_bundle_path],
            check=True
        )
        subprocess.run(
            ["spctl", "-a", "-vv", app_bundle_path],
            check=True
        )
        logging.info("Code signing verification passed!")
    except subprocess.CalledProcessError as e:
        logging.error(f"Code signing verification failed: {e}")
        raise

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Sign macOS app bundle")
    parser.add_argument("--app", required=True, help="Path to .app bundle")
    parser.add_argument("--identity", required=True, help="Signing identity (e.g., 'Developer ID Application: Name (ID)')")
    parser.add_argument("--entitlements", help="Path to entitlements.plist")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.app):
        logging.error(f"App bundle not found: {args.app}")
        sys.exit(1)
    
    try:
        sign_app_bundle(args.app, args.identity, args.entitlements)
    except Exception as e:
        logging.error(f"Signing failed: {e}")
        sys.exit(1)