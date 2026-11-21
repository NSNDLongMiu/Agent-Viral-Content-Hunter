#Requires -Version 5.1

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-HunterForbiddenEnvironmentNames {
    # Keep this list in sync with FORBIDDEN_ENV in backend/hunter/ai/cli_runner.py.
    @(
        'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
        'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX',
        'CLAUDE_CODE_USE_FOUNDRY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CODEX_API_KEY',
        'GEMINI_API_KEY', 'GEMINI_BASE_URL', 'GOOGLE_API_KEY', 'GOOGLE_GENAI_USE_VERTEXAI',
        'GOOGLE_CLOUD_PROJECT', 'GOOGLE_APPLICATION_CREDENTIALS', 'GOOGLE_GEMINI_BASE_URL',
        'GOOGLE_VERTEX_BASE_URL', 'NODE_OPTIONS'
    )
}

function Clear-HunterProviderEnvironment {
    foreach ($name in Get-HunterForbiddenEnvironmentNames) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
}
