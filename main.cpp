/* === S Y N F I G ========================================================= */
/*!	\file gui/main.cpp
**	\brief Synfig Studio Entrypoint with macOS Environment Setup
**
**	\legal
**	Copyright (c) 2002-2005 Robert B. Quattlebaum Jr., Adrian Bentley
**	Copyright (c) 2007, 2008 Chris Moore
**
**	This file is part of Synfig.
**
**	Synfig is free software: you can redistribute it and/or modify
**	it under the terms of the GNU General Public License as published by
**	the Free Software Foundation, either version 2 of the License, or
**	(at your option) any later version.
**
**	Synfig is distributed in the hope that it will be useful,
**	but WITHOUT ANY WARRANTY; without even the implied warranty of
**	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
**	GNU General Public License for more details.
**
**	You should have received a copy of the GNU General Public License
**	along with Synfig.  If not, see <https://www.gnu.org/licenses/>.
**	\endlegal
*/
/* ========================================================================= */

/* === H E A D E R S ======================================================= */

#ifdef USING_PCH
#	include "pch.h"
#else
#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <limits.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>
#endif

#include <glibmm/convert.h>
#include <synfig/os.h>
#include <gui/app.h>
#include <gui/exception_guard.h>
#include <gui/localization.h>

#include <iostream>

#endif

/* === U S I N G =========================================================== */

using namespace synfig;
using namespace studio;

/* === M A C R O S ========================================================= */

/* === G L O B A L S ======================================================= */

/* === P R O C E D U R E S ================================================= */

/* === M E T H O D S ======================================================= */

/* === E N T R Y P O I N T ================================================= */

int main(int argc, char **argv)
{
#ifdef __APPLE__
    // macOS environment setup (migrated from SynfigStudio.sh)
    char path[PATH_MAX];
    uint32_t size = sizeof(path);
    if (_NSGetExecutablePath(path, &size) != 0) {
        std::cerr << "Failed to get executable path" << std::endl;
        return 1;
    }
    std::string execPath(path);
    std::string bundleRoot = execPath.substr(0, execPath.find_last_of('/')); // Contents/MacOS
    std::string cwd = bundleRoot + "/../Resources";
    if (chdir(cwd.c_str()) != 0) {
        std::cerr << "Failed to change working directory to " << cwd << std::endl;
        return 1;
    }

    // Static environment variables
    setenv("GTK_EXE_PREFIX", cwd.c_str(), 1);
    setenv("GTK_DATA_PREFIX", (cwd + "/share").c_str(), 1);
    setenv("GSETTINGS_SCHEMA_DIR", (cwd + "/share/glib-2.0/schemas/").c_str(), 1);
    setenv("FONTCONFIG_PATH", (cwd + "/etc/fonts").c_str(), 1);
    setenv("MLT_DATA", (cwd + "/share/mlt/").c_str(), 1);
    setenv("MLT_REPOSITORY", (cwd + "/lib/mlt/").c_str(), 1);
    std::string currentPath = getenv("PATH") ? getenv("PATH") : "";
    setenv("PATH", (cwd + "/bin:" + cwd + "/synfig-production/bin:" + currentPath).c_str(), 1);
    setenv("SYNFIG_ROOT", cwd.c_str(), 1);
    setenv("SYNFIG_MODULE_LIST", (cwd + "/etc/synfig_modules.cfg").c_str(), 1);
    std::string currentXdgDataDirs = getenv("XDG_DATA_DIRS") ? getenv("XDG_DATA_DIRS") : "";
    setenv("XDG_DATA_DIRS", (cwd + "/share/:" + currentXdgDataDirs).c_str(), 1);
    setenv("GDK_PIXBUF_MODULEDIR", (cwd + "/lib/gdk-pixbuf-2.0/2.10.0/loaders/").c_str(), 1);

    // GDK Pixbuf module file
    std::string home = getenv("HOME");
    std::string moduleFile = home + "/.synfig-gdk-loaders";
    if (access(moduleFile.c_str(), F_OK) == 0) {
        remove(moduleFile.c_str());
    }
    std::string cmd = cwd + "/bin/gdk-pixbuf-query-loaders > " + moduleFile;
    if (system(cmd.c_str()) != 0) {
        std::cerr << "Failed to generate GDK pixbuf module file at " << moduleFile << std::endl;
        return 1;
    }
    setenv("GDK_PIXBUF_MODULE_FILE", moduleFile.c_str(), 1);

    // Python setup
    std::string versionsDir = cwd + "/Frameworks/Python.framework/Versions/";
    DIR* dir = opendir(versionsDir.c_str());
    std::string pythonVersion;
    if (dir) {
        struct dirent* entry;
        while ((entry = readdir(dir)) != nullptr) {
            if (entry->d_type == DT_DIR && entry->d_name[0] != '.') {
                pythonVersion = entry->d_name;
                break;
            }
        }
        closedir(dir);
    }
    if (!pythonVersion.empty()) {
        setenv("PYTHON_VERSION", pythonVersion.c_str(), 1);
        setenv("PYTHONHOME", (versionsDir + pythonVersion + "/").c_str(), 1);
    } else {
        std::cerr << "Warning: Failed to find Python version in " << versionsDir << std::endl;
    }

    // ImageMagick setup
    std::string libDir = cwd + "/lib/";
    std::string magickDir;
    dir = opendir(libDir.c_str());
    if (dir) {
        struct dirent* entry;
        while ((entry = readdir(dir)) != nullptr) {
            if (entry->d_type == DT_DIR && strncmp(entry->d_name, "ImageMagick", 11) == 0) {
                magickDir = entry->d_name;
                break;
            }
        }
        closedir(dir);
    }
    if (!magickDir.empty()) {
        std::string magickLibDir = libDir + magickDir + "/";
        std::string configDir;
        std::string modulesDir;
        dir = opendir(magickLibDir.c_str());
        if (dir) {
            struct dirent* entry;
            while ((entry = readdir(dir)) != nullptr) {
                if (entry->d_type == DT_DIR && entry->d_name[0] != '.') {
                    if (strncmp(entry->d_name, "config-", 7) == 0) {
                        configDir = entry->d_name;
                    } else if (strncmp(entry->d_name, "modules-", 8) == 0) {
                        modulesDir = entry->d_name;
                    }
                }
            }
            closedir(dir);
        }
        if (!configDir.empty() && !modulesDir.empty()) {
            setenv("MAGICK_CONFIGURE_PATH", (magickLibDir + configDir + "/").c_str(), 1);
            setenv("MAGICK_CODER_MODULE_PATH", (magickLibDir + modulesDir + "/coders/").c_str(), 1);
            setenv("MAGICK_CODER_FILTER_PATH", (magickLibDir + modulesDir + "/filters/").c_str(), 1);
        } else {
            std::cerr << "Warning: Failed to find ImageMagick config or modules directories in " << magickLibDir << std::endl;
        }
    } else {
        std::cerr << "Warning: Failed to find ImageMagick directory in " << libDir << std::endl;
    }
#else
    // Non-macOS setup
    synfig::OS::fallback_binary_path = filesystem::Path(Glib::filename_to_utf8(argv[0]));
    const filesystem::Path rootpath = synfig::OS::get_binary_path().parent_path().parent_path();
#endif

#ifdef ENABLE_NLS
    filesystem::Path locale_dir;
#ifdef __APPLE__
    locale_dir = filesystem::Path(getenv("SYNFIG_ROOT")) / filesystem::Path("share/locale");
#else
    locale_dir = rootpath / filesystem::Path("share/locale");
#endif
    setlocale(LC_ALL, "");
    bindtextdomain(GETTEXT_PACKAGE, locale_dir.u8_str());
    bind_textdomain_codeset(GETTEXT_PACKAGE, "UTF-8");
    textdomain(GETTEXT_PACKAGE);
#endif

    std::cout << std::endl;
    std::cout << "   " << _("synfig studio -- starting up application...") << std::endl << std::endl;

    SYNFIG_EXCEPTION_GUARD_BEGIN()

    Glib::RefPtr<studio::App> app = studio::App::instance();

    app->signal_startup().connect([app]() {
#ifdef __APPLE__
        app->init(getenv("SYNFIG_ROOT"));
#else
        app->init(rootpath.u8string());
#endif
    });

    app->register_application();
    if (app->is_remote()) {
        std::cout << std::endl;
        std::cout << "   " << _("synfig studio is already running") << std::endl << std::endl;
        std::cout << "   " << _("the existing process will be used") << std::endl << std::endl;
    }

    int exit_code = app->run(argc, argv);

    std::cerr << "Application appears to have terminated successfully" << std::endl;

    return exit_code;

    SYNFIG_EXCEPTION_GUARD_END_INT(0)
}