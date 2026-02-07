--[[
gopilot.lua - Neovim LSP configuration for gopilot

Installation:
1. Copy this file to your Neovim config directory (e.g., ~/.config/nvim/lua/gopilot.lua)
2. Add require('gopilot').setup() to your init.lua
3. Ensure gopilot is installed and Ollama is running

Usage:
  require('gopilot').setup({
    model = "codellama",           -- Ollama model to use
    ollama_host = "localhost",     -- Ollama server host
    ollama_port = 11434,           -- Ollama server port
    log_level = "INFO",            -- Log level: DEBUG, INFO, WARNING, ERROR
  })
]]

local M = {}

-- Default configuration
M.config = {
  model = "codellama",
  ollama_host = "localhost",
  ollama_port = 11434,
  log_level = "INFO",
  log_file = "/tmp/gopilot.log",
  filetypes = {
    "python",
    "javascript",
    "typescript",
    "javascriptreact",
    "typescriptreact",
    "go",
    "rust",
    "java",
    "c",
    "cpp",
    "ruby",
    "php",
    "lua",
    "sh",
    "bash",
    "sql",
    "html",
    "css",
    "json",
    "yaml",
    "toml",
    "markdown",
  },
  -- Keybinding configuration
  keybindings = {
    hover = "K",           -- Show hover documentation
    definition = "gd",     -- Go to definition (not implemented)
    references = "gr",     -- Show references (not implemented)
    completion = "<C-Space>", -- Trigger completion
    rename = "<leader>rn", -- Rename symbol (not implemented)
    code_action = "<leader>ca", -- Code action (not implemented)
    format = "<leader>f",  -- Format document (not implemented)
  },
  -- Auto completion settings
  auto_completion = true,
  completion_delay = 100, -- ms delay before triggering completion
}

-- Setup function
function M.setup(opts)
  -- Merge user options with defaults
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})

  -- Find gopilot executable
  local gopilot_cmd = M.find_gopilot()
  if not gopilot_cmd then
    vim.notify(
      "gopilot not found. Install with: pip install gopilot",
      vim.log.levels.ERROR
    )
    return
  end

  -- Build server command
  local cmd = {
    gopilot_cmd,
    "--mode", "stdio",
    "--model", M.config.model,
    "--ollama-host", M.config.ollama_host,
    "--ollama-port", tostring(M.config.ollama_port),
    "--log-file", M.config.log_file,
    "--log-level", M.config.log_level,
  }

  -- Configure LSP client
  local client_config = {
    name = "gopilot",
    cmd = cmd,
    filetypes = M.config.filetypes,
    root_dir = function(fname)
      return vim.fn.getcwd()
    end,
    settings = {},
    capabilities = vim.lsp.protocol.make_client_capabilities(),
    on_attach = M.on_attach,
    on_init = function(client)
      vim.notify("gopilot LSP initialized", vim.log.levels.INFO)
    end,
    on_exit = function(code, signal)
      if code ~= 0 then
        vim.notify(
          string.format("gopilot exited with code %d", code),
          vim.log.levels.WARN
        )
      end
    end,
  }

  -- Check if nvim-lspconfig is available
  local has_lspconfig, lspconfig = pcall(require, "lspconfig")
  local has_configs, configs = pcall(require, "lspconfig.configs")

  if has_lspconfig and has_configs then
    -- Register gopilot with nvim-lspconfig
    if not configs.gopilot then
      configs.gopilot = {
        default_config = {
          cmd = cmd,
          filetypes = M.config.filetypes,
          root_dir = function(fname)
            return vim.fn.getcwd()
          end,
          settings = {},
        },
      }
    end

    -- Setup the server
    lspconfig.gopilot.setup({
      capabilities = client_config.capabilities,
      on_attach = client_config.on_attach,
      on_init = client_config.on_init,
      on_exit = client_config.on_exit,
    })
  else
    -- Use native vim.lsp.start without nvim-lspconfig
    vim.api.nvim_create_autocmd("FileType", {
      pattern = M.config.filetypes,
      callback = function(args)
        vim.lsp.start(client_config, { bufnr = args.buf })
      end,
    })
  end

  -- Setup autocommands
  M.setup_autocommands()

  vim.notify("gopilot configured successfully", vim.log.levels.INFO)
end

-- Find gopilot executable
function M.find_gopilot()
  -- Check if gopilot is in PATH
  local handle = io.popen("which gopilot 2>/dev/null")
  if handle then
    local result = handle:read("*a")
    handle:close()
    if result and result ~= "" then
      return result:gsub("%s+", "")
    end
  end

  -- Try running as Python module
  local python_paths = { "python3", "python" }
  for _, python in ipairs(python_paths) do
    local check = io.popen(python .. " -c 'import gopilot' 2>/dev/null")
    if check then
      local result = check:read("*a")
      check:close()
      -- If no error, module exists
      return python .. " -m gopilot.server"
    end
  end

  return nil
end

-- LSP on_attach callback
function M.on_attach(client, bufnr)
  local opts = { noremap = true, silent = true, buffer = bufnr }
  local keymap = M.config.keybindings

  -- Hover documentation
  if keymap.hover then
    vim.keymap.set("n", keymap.hover, vim.lsp.buf.hover, opts)
  end

  -- Definition (placeholder - not implemented in gopilot)
  if keymap.definition then
    vim.keymap.set("n", keymap.definition, vim.lsp.buf.definition, opts)
  end

  -- References (placeholder - not implemented in gopilot)
  if keymap.references then
    vim.keymap.set("n", keymap.references, vim.lsp.buf.references, opts)
  end

  -- Completion trigger
  if keymap.completion then
    vim.keymap.set("i", keymap.completion, function()
      vim.lsp.buf.completion()
    end, opts)
  end

  -- Rename (placeholder - not implemented in gopilot)
  if keymap.rename then
    vim.keymap.set("n", keymap.rename, vim.lsp.buf.rename, opts)
  end

  -- Code action (placeholder - not implemented in gopilot)
  if keymap.code_action then
    vim.keymap.set("n", keymap.code_action, vim.lsp.buf.code_action, opts)
  end

  -- Format (placeholder - not implemented in gopilot)
  if keymap.format then
    vim.keymap.set("n", keymap.format, function()
      vim.lsp.buf.format({ async = true })
    end, opts)
  end

  -- Display server capabilities
  vim.notify(
    string.format("gopilot attached to buffer %d", bufnr),
    vim.log.levels.DEBUG
  )
end

-- Setup autocommands
function M.setup_autocommands()
  local group = vim.api.nvim_create_augroup("Gopilot", { clear = true })

  -- Auto-completion on text change (if enabled)
  if M.config.auto_completion then
    vim.api.nvim_create_autocmd({ "TextChangedI", "TextChangedP" }, {
      group = group,
      callback = function()
        -- Debounce completion requests
        vim.defer_fn(function()
          -- Only trigger if still in insert mode
          if vim.fn.mode() == "i" then
            -- Trigger omnifunc or built-in completion
            -- Note: This is a basic implementation
            -- For better experience, use nvim-cmp with gopilot
          end
        end, M.config.completion_delay)
      end,
    })
  end
end

-- Health check function for :checkhealth gopilot
function M.health()
  local health = vim.health or require("health")
  local start = health.start or health.report_start
  local ok = health.ok or health.report_ok
  local warn = health.warn or health.report_warn
  local error_fn = health.error or health.report_error

  start("gopilot")

  -- Check for gopilot executable
  local gopilot_cmd = M.find_gopilot()
  if gopilot_cmd then
    ok("gopilot executable found: " .. gopilot_cmd)
  else
    error_fn("gopilot not found. Install with: pip install gopilot")
  end

  -- Check Python version
  local python_version = vim.fn.system("python3 --version 2>&1")
  if python_version:match("Python 3%.1[0-2]") then
    ok("Python 3.10+ found: " .. python_version:gsub("%s+$", ""))
  else
    warn("Python 3.10+ required: " .. python_version:gsub("%s+$", ""))
  end

  -- Check Ollama availability
  local ollama_url = string.format(
    "http://%s:%d/api/tags",
    M.config.ollama_host,
    M.config.ollama_port
  )
  local curl_result = vim.fn.system("curl -s " .. ollama_url .. " 2>&1")
  if curl_result:match('"models"') then
    ok("Ollama server is running at " .. M.config.ollama_host .. ":" .. M.config.ollama_port)

    -- List available models
    local models_json = vim.fn.json_decode(curl_result)
    if models_json and models_json.models then
      local model_names = {}
      for _, model in ipairs(models_json.models) do
        table.insert(model_names, model.name)
      end
      if #model_names > 0 then
        ok("Available models: " .. table.concat(model_names, ", "))
      end
    end
  else
    warn("Ollama server not reachable at " .. M.config.ollama_host .. ":" .. M.config.ollama_port)
    warn("Start Ollama with: ollama serve")
  end

  -- Check for nvim-lspconfig
  local has_lspconfig = pcall(require, "lspconfig")
  if has_lspconfig then
    ok("nvim-lspconfig is installed")
  else
    warn("nvim-lspconfig not found (optional, but recommended)")
  end
end

-- Register health check
vim.api.nvim_create_autocmd("User", {
  pattern = "CheckHealth",
  callback = function()
    M.health()
  end,
})

return M
