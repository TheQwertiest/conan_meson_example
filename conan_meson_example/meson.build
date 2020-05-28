project('example', 
        'cpp', 
        default_options: [
            'prefix=' + meson.source_root()/'../_result',
            'cpp_std=c++14'
        ])

exe_codegen = executable('codegen', 'codegen.cpp')
src_generated = custom_target('generate_src', command: [exe_codegen, '@OUTPUT@'], output: 'main.cpp')
executable('example', src_generated, install: true)
