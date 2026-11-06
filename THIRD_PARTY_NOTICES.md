# Third-party notices

Runtime image включает следующие закреплённые третьи компоненты:

| Компонент | Revision/artifact | Лицензия | Официальный источник |
|---|---|---|---|
| IndexTeam Index-Translate-9B-GGUF | revision `645939fbab839a656f1bc39975a872bc8ad749f8`, `Index-Translate-9B.Q4_K_M.gguf`, SHA-256 из `provider.lock.json` | Apache-2.0 | https://huggingface.co/IndexTeam/Index-Translate-9B-GGUF |
| ggml-org/llama.cpp | commit `d81235049384534c167caea52b85a694f6103d14` | MIT | https://github.com/ggml-org/llama.cpp |

Полные license texts устанавливаются в `/licenses` runtime image из
официальных источников с закреплённым SHA-256. License metadata модели также
зафиксирована в pinned model card и проверяется `provider.lock.json`.
