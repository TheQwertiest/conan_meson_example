from conans import ConanFile, Meson, tools
from conans.client.tools.env import _environment_add, environment_append
from conans.errors import ConanException

import os
import platform
from pathlib import Path
from configparser import ConfigParser


class ConanHackedMeson(Meson):
    """
    Hacked `conans.Mesons`: 
    - `_run()`: does not add deps info to environment variables anymore
    """
    def _run(self, command):
        def _build():
            self._conanfile.run(command)
        if self._vcvars_needed:
            vcvars_dict = tools.vcvars_dict(self._settings, output=self._conanfile.output)
            with _environment_add(vcvars_dict, post=self._append_vcvars):
                _build()
        else:
            _build()

class MesonMachineFile:
    def __init__(self,
                 name: str,
                 path: str = None,
                 config: ConfigParser = None):
        if not name:
            raise ConanException('`name` is empty: machine file must have a unique name supplied')
        self.name = name

        if path and config:
            raise ConanException('Both `path` and `config` were supplied: only one should be used')
        if path:
            config = ConfigParser()
            config.read(path)
        self.options = config

    def dump(self, output: str):
        outpath = Path(output)
        if not outpath.exists():
            outpath.mkdir(parents=True)
        with open(outpath/self.name, 'w') as f:
            self.options.write(f)

class MesonToolchain:
    def __init__(self, native_files = None, cross_files = None ):
        self.native_files = native_files or []
        self.cross_files = cross_files or []

    def __iter__(self):
        for i in [self.native_files, self.cross_files]:
            yield i

    def dump(self, output: str):
      if self.native_files:
        outpath = Path(output) / 'native'
        if not outpath.exists():
            outpath.mkdir(parents=True)
        for f in self.native_files:
          f.dump(outpath)
      if self.cross_files:
        outpath = Path(output) / 'cross'
        if not outpath.exists():
            outpath.mkdir(parents=True)
        for f in self.cross_files:
          f.dump(outpath)

class MesonDefaultToolchainGenerator(object):
    def __init__(self, conanfile):
        self._conanfile = conanfile

    def generate(self, force_cross: bool = False) -> MesonToolchain:
        mt = MesonToolchain()
        if hasattr(self._conanfile, 'settings_build') and self._conanfile.settings_build:
            mt.native_files += [MesonMachineFile(name='default.ini', config=self._dict_to_config(self._create_native(self._conanfile.settings_build, True)))]
        if hasattr(self._conanfile, 'settings_target') and self._conanfile.settings_target:
            mt.cross_files += [MesonMachineFile(name='default.ini', config=self._dict_to_config(self._create_cross(self._conanfile.settings_target)))]
        if (not (hasattr(self._conanfile, 'settings_build') and self._conanfile.settings_build) and 
            not (hasattr(self._conanfile, 'settings_target') and self._conanfile.settings_target)):
            tmp_native_files, tmp_cross_files = self._create_machine_files_from_settings(self._conanfile.settings, force_cross)
            mt.native_files += tmp_native_files
            mt.cross_files += tmp_cross_files
        return mt

    def _dict_to_config(self, machine_dict: dict) -> ConfigParser:
        config = ConfigParser()
        config.read_dict(self._to_ini(machine_dict))
        return config

    def _to_ini(self, config):
        return {section_name: {key: self._to_ini_value(value) for key, value in section.items() if value is not None}
                for section_name, section in config.items()}

    def _to_ini_value(self, value):
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, str):
            return "'{}'".format(value)
        return value

    def _create_native(self, settings, is_separate_profile: bool) -> dict:
        def none_if_empty(input: str):
            stripped_input = input.strip()
            return stripped_input if stripped_input else None
        def env_or_for_build(input: str, is_separate_profile, default_val = None):
            if is_separate_profile:
                return os.environ.get(input, default_val)
            else:
                return os.environ.get('{}_FOR_BUILD'.format(input), default_val)
        def atr_or_for_build(settings, input: str, is_separate_profile):
            if is_separate_profile:
                return settings.get_safe(input)
            else:
                return settings.get_safe('{}_build'.format(input))

        config_template = {
            'binaries': {
                'c': env_or_for_build('CC', is_separate_profile),
                'cpp': env_or_for_build('CXX', is_separate_profile),
                'ld': env_or_for_build('LD', is_separate_profile),
                'ar': env_or_for_build('AR', is_separate_profile),
                'strip': env_or_for_build('STRIP', is_separate_profile),
                'as': env_or_for_build('AS', is_separate_profile),
                'ranlib': env_or_for_build('RANLIB', is_separate_profile),
                'pkgconfig': tools.which('pkg-config')
            },
            'properties': {
                'c_args': none_if_empty(env_or_for_build('CPPFLAGS', is_separate_profile, '') + ' ' + env_or_for_build('CFLAGS', is_separate_profile, '')),
                'cpp_args': none_if_empty(env_or_for_build('CPPFLAGS', is_separate_profile, '') + ' ' + env_or_for_build('CXXFLAGS', is_separate_profile, '')),
                'c_link_args': env_or_for_build('LDFLAGS', is_separate_profile),
                'cpp_link_args': env_or_for_build('LDFLAGS', is_separate_profile),
                'pkg_config_path': env_or_for_build('PKG_CONFIG_PATH', is_separate_profile),
            }
        }

        if atr_or_for_build(settings, 'os', is_separate_profile):
            resolved_os = atr_or_for_build(settings, 'os', is_separate_profile)
            arch = atr_or_for_build(settings, 'arch', is_separate_profile)
            cpu_family, endian = self._get_cpu_family_and_endianness_from_arch(str(arch))
            config_template['build_machine'] = {
                'system': self._get_system_from_os(str(resolved_os)),
                'cpu': str(arch),
                'cpu_family': cpu_family,
                'endian': endian,
            }

        return config_template

    def _create_cross(self, settings) -> dict:
        def none_if_empty(input: str):
            stripped_input = input.strip()
            return stripped_input if stripped_input else None

        config_template = {
            'binaries': {
                'c': os.environ.get('CC'),
                'cpp': os.environ.get('CXX'),
                'ld': os.environ.get('LD'),
                'ar': os.environ.get('AR'),
                'strip': os.environ.get('STRIP'),
                'as': os.environ.get('AS'),
                'ranlib': os.environ.get('RANLIB'),
                'pkgconfig': tools.which('pkg-config')
            },
            'properties': {
                'c_args': none_if_empty(os.environ.get('CPPFLAGS', '') + ' ' + os.environ.get('CFLAGS', '')),
                'cpp_args': none_if_empty(os.environ.get('CPPFLAGS', '') + ' ' + os.environ.get('CXXFLAGS', '')),
                'c_link_args': os.environ.get('LDFLAGS'),
                'cpp_link_args': os.environ.get('LDFLAGS'),
                'pkg_config_path': os.environ.get('PKG_CONFIG_PATH'),
                'needs_exe_wrapper': tools.cross_building(settings),
            },
            'host_machine': {
                'system': self._get_system_from_os(str(settings.os)),
                'cpu': str(settings.arch)
            }
        }

        cpu_family, endian = self._get_cpu_family_and_endianness_from_arch(str(settings.arch))
        config_template['host_machine']['cpu_family'] = cpu_family
        config_template['host_machine']['endian'] = endian

        if not config_template['binaries']['c'] and not config_template['binaries']['cpp']:
            raise ConanException(f'CC and CXX are undefined: C or C++ compiler must be defined when cross-building')

        return config_template

    def _create_machine_files_from_settings(self, settings, force_cross: bool):
        is_cross = force_cross
        has_for_build = False

        if not is_cross:
            has_for_build = any(map(lambda e: os.environ.get(e), ['CC_FOR_BUILD', 'CXX_FOR_BUILD']))
            is_cross = has_for_build or any(map(lambda a: hasattr(settings, a), ['os_build', 'arch_build']))

        native_files = []
        if has_for_build or not is_cross:
            native_files += [MesonMachineFile(name='default.ini', config=self._dict_to_config(self._create_native(settings, False)))]

        cross_files = []
        if is_cross:
            cross_files += [MesonMachineFile(name='default.ini', config=self._dict_to_config(self._create_cross(settings)))]

        return (native_files, cross_files)

    @staticmethod
    def _get_system_from_os(os: str) -> str:
        """
        Converts from `conan/conans/client/conf/__init__.py` to `https://mesonbuild.com/Reference-tables.html#operating-system-names`
        """
        os = os.lower()
        if (os == 'macos' or os == 'ios'):
            return 'darwin'
        else:
            return os

    @staticmethod
    def _get_cpu_family_and_endianness_from_arch(arch: str):
        """
        Converts from `conan/conans/client/conf/__init__.py` to `https://mesonbuild.com/Reference-tables.html#cpu-families`
        """
        arch_to_cpu = {
            'x86' : ('x86', 'little'),
            'x86_64' : ('x86_64',  'little'),
            'x86' : ('x86', 'little'),
            'ppc32be' : ('ppc', 'big'),
            'ppc32' : ('ppc', 'little'),
            'ppc64le' : ('ppc64', 'little'),
            'ppc64' : ('ppc64', 'big'),
            'armv4' : ('arm', 'little'),
            'armv4i' : ('arm', 'little'),
            'armv5el' : ('arm', 'little'),
            'armv5hf' : ('arm', 'little'),
            'armv6' : ('arm', 'little'),
            'armv7' : ('arm', 'little'),
            'armv7hf' : ('arm', 'little'),
            'armv7s' : ('arm', 'little'),
            'armv7k' : ('arm', 'little'),
            'armv8_32' : ('arm', 'little'),
            'armv8' : ('aarch64', 'little'),
            'armv8.3' : ('aarch64', 'little'),
            'sparc' : ('sparc', 'big'),
            'sparcv9' : ('sparc64', 'big'),
            'mips' : ('mips', 'big'),
            'mips64' : ('mips64', 'big'),
            'avr' : ('avr', 'little'),
            's390' : ('s390', 'big'),
            's390x' : ('s390', 'big'),
            'wasm' : ('wasm', 'little'),
        }

        if (arch not in arch_to_cpu):
            raise ConanException('Unknown arch: {}'.format(arch))

        return arch_to_cpu[arch]


class ExampleConanMeson(ConanFile):
    name = 'conan_meson_example'
    version = '1.0.0'
    _source_subfolder = name
    exports_sources = [_source_subfolder + '/*']

    settings =  'os', 'compiler', 'arch', 'build_type', 'arch_build', 'os_build'
    build_requires = ('meson/[>=0.54.0]', 'ninja/[>=1.9.0]')

    generators = 'pkg_config'

    def build(self):
        self._get_configured_module().build(build_dir=self._current_build_path)

    def package(self):
        self._get_configured_module().install(build_dir=self._current_build_path)

    def _get_configured_module(self):        
        self._current_build_path = Path(self.build_folder)/'_meson'
        machine_file_path = Path(self.build_folder)/'_meson_machine_files'

        module = ConanHackedMeson(self)

        mt = MesonDefaultToolchainGenerator(self).generate()
        mt.dump(machine_file_path)

        configure_args = [
            f'-Dprefix={self.package_folder}',
        ]
        
        if (machine_file_path / 'native').exists:
            configure_args += [f'--native-file={f}' for f in list((machine_file_path / 'native').glob('*'))]
        if (machine_file_path / 'cross').exists:
            configure_args += [f'--cross-file={f}' for f in list((machine_file_path / 'cross').glob('*'))]
      
        # Don't pass flags via env: we are using machine files for that purpose
        env_vars_to_clean = {
            'CC',
            'CXX',
            'CCFLAGS',
            'CXXFLAGS',
            'CPPFLAGS',
            'LDFLAGS',
            'AR',
            'AS',
            'STRIP',
            'RANLIB',
        }
        clean_env = {ev: None for ev in env_vars_to_clean}
        clean_env.update({'{}_FOR_BUILD'.format(ev): None for ev in env_vars_to_clean})
            
        with environment_append(clean_env):
            module.configure(source_folder=self._source_subfolder,
                             build_folder=self._current_build_path,
                             args=configure_args)

        return module
