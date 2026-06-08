local dap_defaults = {
  request = 'launch',
  type = 'python',
  args = { 'jpgs/without.jpg' },
}

local flask_set_GPSIFD = vim.tbl_extend(
  'force',
  {
    program = vim.fn.expand('src/flask_set_GPSIFD.py'),
    name = 'Set GPSIFD with Flask',
  },
  dap_defaults
)


return {
  flask_set_GPSIFD,
}
