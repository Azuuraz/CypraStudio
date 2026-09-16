# Security Policy

CypraStudio is a local-first desktop application that combines a native WebView2 shell, a loopback FastAPI service, and a private Ollama runtime. Security decisions are centered on keeping local application boundaries explicit, limiting remote behavior, and preventing imported or browser-originated data from silently becoming trusted instructions or executable content.

## Supported version

Security fixes are maintained against the current CypraStudio release line. When reporting an issue, reproduce it on the newest available build when practical.

## Security model

CypraStudio currently uses the following protections:

- The application backend is intended for loopback access only.
- HTTP Host values are validated for the local trust boundary.
- Cross-site browser requests are rejected, including cross-site GET requests.
- State-changing requests are protected by same-origin validation.
- Browser-facing responses apply Content Security Policy, frame, MIME-sniffing, and referrer protections.
- Request bodies are bounded, including streamed/chunked requests.
- Uploaded background images are checked by file signature instead of trusting only the supplied MIME type.
- Session/model identifiers and application filesystem operations are constrained to expected forms and project-owned locations.
- Ollama traffic is constrained to a loopback HTTP endpoint.
- `OLLAMA_MODELS` is reasserted to CypraStudio's project-local `OllamaModels` directory so a parent environment cannot silently redirect the application to a host/global model store.
- Runtime ownership information is tracked so project-owned Ollama processes can be identified and shut down deliberately.
- Hugging Face imports accept GGUF model data only. Repository scripts and arbitrary code are not executed as part of the import path.
- Hugging Face downloads are size-bounded, commit-pinned, space-checked, and SHA-256 verified before registration.
- Edge neural TTS is disabled unless the user explicitly enables online Edge TTS.
- Text is sanitized before optional Edge speech synthesis. Credential-shaped material, internal prompt/context markers, private paths, and configured code/URL content are excluded from online speech requests.
- Piper TTS is designed to run locally and CPU-only so voice output does not compete with the configured local model for GPU VRAM.
- Persistent JSON state uses atomic-write behavior and keeps a last-known-good settings recovery copy.

These controls reduce risk; they do not turn the application, the operating system, third-party models, or optional network services into a formal security boundary.

## Network behavior

Normal local chat is intended to use the private loopback Ollama runtime. CypraStudio may access the network when the user explicitly invokes functionality that requires it, including:

- online Python dependency installation when offline setup resources are unavailable;
- public Hugging Face repository inspection or GGUF downloads;
- Microsoft Edge neural TTS after its online privacy gate has been enabled.

Browser/device speech and local Piper speech do not require Edge TTS.

Do not enable an online feature for data that must remain strictly local.

## Model and content trust

Downloaded models, model responses, retrieved documents, imported conversations, and user-provided files should be treated as untrusted content.

CypraStudio's local retrieval layer injects retrieved material as reference context rather than executable application instructions. This reduces prompt-injection risk but does not guarantee that a language model will ignore malicious or misleading content. Review consequential model output before acting on it.

## Local-machine trust

CypraStudio is not designed to defend project data from an attacker who already has unrestricted access to the Windows user account, project directory, Python environment, process memory, browser profile, or administrator privileges.

Protect the host operating system, account credentials, and project directory using normal Windows security practices.

## Reporting a vulnerability

Please avoid publishing working exploit details in a public issue before the maintainer has had a reasonable opportunity to investigate.

Preferred reporting method:

1. Use the repository's **Private vulnerability reporting / Security advisory** feature when available.
2. Include the CypraStudio build identifier and Windows version.
3. Describe the affected component and exact reproduction steps.
4. State whether the issue requires a remote website, local file, local process, user interaction, or elevated privileges.
5. Include sanitized logs, screenshots, or a minimal proof of concept when they materially help reproduce the problem.
6. Do not include passwords, API keys, tokens, private prompts, private conversations, or unrelated personal data.

If private repository reporting is unavailable, contact the maintainer through the repository owner's published contact channel and request a private reporting path before sharing exploit details.

## What to report

Useful security reports include, but are not limited to:

- bypasses of the loopback/Host/origin boundary;
- cross-site requests that can read or change Studio state;
- arbitrary file read/write or path traversal outside project-owned locations;
- command or code execution caused by imported content or repository metadata;
- unexpected transmission of prompts, conversations, credentials, or local paths to a remote service;
- unsafe Hugging Face download or registration behavior;
- authentication/trust-boundary mistakes in future remote-access features;
- process-lifecycle bugs that cause CypraStudio to terminate unrelated applications or attach to an unrelated Ollama runtime.

General model quality issues, prompt behavior, or inaccurate model responses are not security vulnerabilities unless they cross an application security boundary or cause unintended privileged action.

## Security-sensitive defaults

When changing CypraStudio, preserve these defaults unless a deliberate design change requires otherwise:

- loopback-only application/runtime communication;
- project-local model storage;
- no automatic execution of downloaded repository code;
- Edge TTS online access off unless explicitly enabled;
- bounded request/download sizes;
- explicit validation at filesystem, HTTP, process, and network boundaries;
- no silent expansion from local features into remote services.

## Disclosure

Reasonable coordinated disclosure is encouraged. A useful report is one that gives enough information to reproduce and fix the defect without unnecessarily exposing users to a public exploit before a fix is available.
