project('satdeploy-apm', 'c', subproject_dir: 'lib', version: '0.1.0', default_options: [
  'default_library=static',
  'b_lto=false',
  'b_lundef=false',
  'csp:packet_padding_bytes=42',
  'csp:buffer_count=1000',
  'csp:buffer_size=2048',
  'csp:conn_max=20',
  'csp:conn_rxqueue_len=1000',
  'csp:qfifo_len=1000',
  'csp:rdp_max_window=1000',
  'csp:port_max_bind=16',
  'csp:use_rtable=true',
])

includes = include_directories('src')
apm_csh_dep = dependency('apm_csh', fallback: ['apm_csh', 'apm_csh_dep'], required: true)
# CSP: headers + compile_args only — actual CSP functions come from CSH at runtime.
# Linking the static CSP lib would embed uninitialized CSP globals that shadow CSH's.
csp_dep = dependency('csp', fallback: ['csp', 'csp_dep'], required: true).partial_dependency(includes: true, compile_args: true)
slash_dep = dependency('slash', fallback: ['slash', 'slash_dep'], required: false).partial_dependency(links: false, includes: true)
param_dep = dependency('param', fallback: ['param', 'param_dep']).as_link_whole()
proto_c_dep = dependency('libprotobuf-c', fallback: ['protobuf-c', 'libprotobuf_c_dep'])
yaml_dep = dependency('yaml-0.1', fallback: ['libyaml', 'yaml_dep'], required: true)
sqlite3_dep = dependency('sqlite3', fallback: ['sqlite3', 'sqlite3_dep'], required: true)
# DTP: compile needed source files directly instead of linking libdtp.
# Linking the full DTP library would pull static copies of libcsp and libparam
# into this shared library. When CSH dlopen()s us, those duplicate globals
# (uninitialized) shadow CSH's own initialized copies, causing a segfault.
# By compiling only the DTP sources we need, their CSP/param references stay
# unresolved in the .so (b_lundef=false) and resolve at dlopen time against
# CSH's already-initialized symbols.
dtp_root = 'lib/dtp'
dtp_inc = include_directories(dtp_root / 'include', dtp_root / 'src')

dtp_sources = [
    dtp_root / 'src/dtp_server.c',
    dtp_root / 'src/dtp_file_payload.c',
    dtp_root / 'src/dtp_protocol.c',
    dtp_root / 'src/dtp_os_hal.c',
    dtp_root / 'src/dtp_log.c',
]

satdeploy_apm = shared_library(
    'csh_satdeploy_apm',
    [
      'src/satdeploy_apm.c',
      'src/sha256.c',
      'src/deploy.pb-c.c',
      'src/config.c',
      'src/output.c',
      'src/history.c',
    ] + dtp_sources,
    include_directories: [includes, dtp_inc],
    dependencies: [apm_csh_dep, slash_dep, param_dep, csp_dep, proto_c_dep, yaml_dep, sqlite3_dep],
    link_args: ['-lm'],
    install: true
)
