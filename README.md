# gopilot

AI-powered Language Server Protocol (LSP) server for Neovim using local Ollama models.

## Features

- **Code Completion** - Context-aware code completions powered by AI
- **Hover Documentation** - AI-generated explanations for code under cursor
- **Multi-model Support** - Works with codellama, deepseek-coder, qwen2.5-coder, and more
- **Docker Integration** - Easy deployment with Docker and docker-compose
- **Flexible Configuration** - CLI arguments and Neovim configuration options
- **Comprehensive Logging** - Debug logs to `/tmp/gopilot.log`
- **Error Resilience** - Graceful handling of Ollama connection failures

## Requirements

- Python 3.10+
- Neovim 0.8+
- [Ollama](https://ollama.ai/) running locally or in Docker
- (Optional) [nvim-lspconfig](https://github.com/neovim/nvim-lspconfig)

## Installation

### 1. Install gopilot

```bash
# Clone the repository
git clone https://github.com/anorien90/gopilot.git
cd gopilot

# Install with pip
pip install -e .
```

### 2. Install Ollama and a Model

```bash
# Install Ollama (macOS/Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a code model
ollama pull codellama

# Or use Docker
docker run -d -v ollama:/root/.ollama -p 11434:11434 --name ollama ollama/ollama
docker exec -it ollama ollama pull codellama
```

### 3. Configure Neovim

Copy the Lua configuration to your Neovim config:

```bash
# Create directory if needed
mkdir -p ~/.config/nvim/lua

# Copy configuration
cp nvim/gopilot.lua ~/.config/nvim/lua/
```

Add to your `init.lua`:

```lua
-- Basic setup
require('gopilot').setup()

-- Or with custom options
require('gopilot').setup({
  model = "codellama",           -- Ollama model to use
  ollama_host = "localhost",     -- Ollama server host
  ollama_port = 11434,           -- Ollama server port
  log_level = "INFO",            -- Log level: DEBUG, INFO, WARNING, ERROR
})
```

## Usage

### Neovim

Once configured, gopilot automatically attaches to supported file types. Use the following keybindings:

| Key | Action | Description |
|-----|--------|-------------|
| `K` | Hover | Show AI-generated documentation |
| `<C-Space>` | Completion | Trigger code completion |
| `gd` | Definition | Go to definition (placeholder) |
| `gr` | References | Find references (placeholder) |
| `<leader>rn` | Rename | Rename symbol (placeholder) |
| `<leader>ca` | Code Action | Show code actions (placeholder) |
| `<leader>f` | Format | Format document (placeholder) |

### CLI Reference

Run gopilot directly from the command line:

```bash
# Stdio mode (default, for Neovim)
gopilot --mode stdio --model codellama

# TCP mode (for remote/Docker usage)
gopilot --mode tcp --host 0.0.0.0 --port 2087

# Full options
gopilot \
  --mode stdio \
  --ollama-host localhost \
  --ollama-port 11434 \
  --model codellama \
  --log-file /tmp/gopilot.log \
  --log-level DEBUG
```

#### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode` | `stdio` | Server mode: `stdio` or `tcp` |
| `--host` | `127.0.0.1` | TCP host (tcp mode only) |
| `--port` | `2087` | TCP port (tcp mode only) |
| `--ollama-host` | `localhost` | Ollama server hostname |
| `--ollama-port` | `11434` | Ollama server port |
| `--model` | `codellama` | Ollama model to use |
| `--log-file` | `/tmp/gopilot.log` | Log file path |
| `--log-level` | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR |

## Docker

### Quick Start with Docker Compose

```bash
# Start Ollama and gopilot
docker-compose up -d

# Pull a model (first time only)
docker exec -it gopilot-ollama ollama pull codellama
```

### Build and Run Manually

```bash
# Build the image
docker build -t gopilot .

# Run the server
docker run -d \
  --name gopilot-server \
  -p 2087:2087 \
  gopilot \
  --mode tcp \
  --host 0.0.0.0 \
  --port 2087 \
  --ollama-host host.docker.internal \
  --ollama-port 11434
```

## Model Recommendations

| Model | Size | Use Case | Speed |
|-------|------|----------|-------|
| `codellama:7b` | 3.8GB | General code completion | Fast |
| `codellama:13b` | 7.4GB | Better quality completions | Medium |
| `codellama:34b` | 19GB | Highest quality | Slow |
| `deepseek-coder:6.7b` | 3.8GB | Multi-language support | Fast |
| `deepseek-coder:33b` | 19GB | Complex completions | Slow |
| `qwen2.5-coder:7b` | 4.4GB | Latest architecture | Fast |
| `starcoder2:7b` | 4.0GB | Multi-language | Fast |

### Pull a model

```bash
ollama pull codellama:7b
# or
ollama pull deepseek-coder:6.7b
```

## Troubleshooting

### Check gopilot health

In Neovim, run:

```vim
:checkhealth gopilot
```

### View logs

```bash
tail -f /tmp/gopilot.log
```

### Common Issues

#### "gopilot not found"

Ensure gopilot is installed and in your PATH:

```bash
pip install -e /path/to/gopilot
which gopilot
```

#### "Ollama server not reachable"

1. Check if Ollama is running:
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. Start Ollama:
   ```bash
   ollama serve
   ```

3. If using Docker, check the container:
   ```bash
   docker ps | grep ollama
   docker logs ollama
   ```

#### "No completions received"

1. Check if a model is installed:
   ```bash
   ollama list
   ```

2. Pull a model:
   ```bash
   ollama pull codellama
   ```

3. Increase log level to DEBUG:
   ```lua
   require('gopilot').setup({ log_level = "DEBUG" })
   ```

#### Slow completions

1. Use a smaller model (7B instead of 13B/34B)
2. Ensure you have enough RAM (at least 8GB for 7B models)
3. Consider GPU acceleration if available

## Supported Languages

gopilot supports completions for:

- Python
- JavaScript / TypeScript
- Go
- Rust
- Java
- C / C++
- Ruby
- PHP
- Lua
- Shell (Bash, Zsh)
- SQL
- HTML / CSS
- JSON / YAML / TOML
- Markdown

## Architecture

```
┌─────────────────┐     LSP Protocol      ┌─────────────────┐
│                 │◄────────────────────► │                 │
│     Neovim      │      (stdio/tcp)      │     gopilot     │
│                 │                       │   LSP Server    │
└─────────────────┘                       └────────┬────────┘
                                                   │
                                                   │ HTTP API
                                                   │
                                          ┌────────▼────────┐
                                          │                 │
                                          │     Ollama      │
                                          │   (localhost)   │
                                          │                 │
                                          └─────────────────┘
```

## Development

### Run tests

```bash
# Install dev dependencies
pip install pytest pytest-cov

# Run tests
pytest tests/
```

### Code style

```bash
# Install formatters
pip install black ruff

# Format code
black gopilot/
ruff check gopilot/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
