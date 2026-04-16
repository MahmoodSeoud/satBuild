project('libcsp-py3', 'c',
  version: '2.2.0',
  license: 'LGPL',
  meson_version: '>=0.61.2',
  default_options: [
    'c_std=gnu11',
    'optimization=s',
    'warning_level=2',
    'werror=false',
  ],
)

# Pull libcsp as a static subproject (source in subprojects/csp/)
csp_proj = subproject('csp',
  default_options: [
    'default_library=static',
    'use_rdp=true',
    'use_rtable=true',
    'enable_python3_bindings=false',
    'buffer_size=4096',
    'buffer_count=100',
    'werror=false',
  ],
)

csp_dep = csp_proj.get_variable('csp_dep')

py = import('python').find_installation('python3')
pydep = dependency('python3', version: '>=3.5', required: true)

# Build the Python extension module from libcsp's pycsp.c
# The source lives in the csp subproject directory
py.extension_module('libcsp_py3',
  'pycsp.c',
  c_args: [
    '-Wno-missing-prototypes',
    '-Wno-unused-parameter',
  ],
  dependencies: [csp_dep, pydep],
  install: true,
)
