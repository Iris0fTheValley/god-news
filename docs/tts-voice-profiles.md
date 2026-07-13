# 多情绪角色语音档案

角色档案使用与 DSakiko `reference_audio_and_text.json` 相同的结构：

```json
{
  "emotion_refs": {
    "happiness": {"audio_path": "J:/.../happy.wav", "text": "参考文本"},
    "sadness": {"audio_path": "J:/.../sad.wav", "text": "参考文本"}
  }
}
```

实际启用 TTS 的角色必须同时具备以下内容：`tts_enabled=true`、成对的
`gpt_weights_path` / `sovits_weights_path`、`tts_model_profile`、可选的
`reference_language`（未填时回退到部署全局值），以及
`happiness`、`sadness`、`anger`、`disgust`、`like`、`surprise`、`fear` 七项完整
`emotion_refs`。每段口播只在这七个参考音频与文本之间切换；同一权重对不会因
情绪而重载模型。

未启用 TTS 的旧角色可以保留不完整的旧权重元数据，以便历史审计；它们不会被合成器
选中。`slug` 在创建后不可修改，已停用角色也会保留历史引用。

如果仍可合成的脚本引用了某个 `speaker_id`，服务会拒绝启用、停用或替换该 speaker 的 TTS
选择字段（权重、模型 profile、参考语言、七情绪参考材料等）。先渲染或归档这些脚本，再变更角色，
避免已审核脚本在合成时悄然换声。

`GOD_NEWS_TTS_TRUSTED_ASSET_ROOTS` 是本地路径白名单。默认列出 GPT-SoVITS 与
`J:/AI friend/DSakiko3.10`，仅为本机示例；部署时应在 `.env` 覆盖。合成前会验证权重、
WAV 和参考文本均位于白名单中。模型和音频始终原地复用，不复制到仓库。

如需把 DSakiko 的 JSON 和同目录 `reference_audio_language.txt` 显式映射到角色表单输入，可调用：

```python
from pathlib import Path
from god_news.infrastructure.tts.dsakiko import load_dsakiko_voice_assets

assets = load_dsakiko_voice_assets(
    config_path=Path("J:/AI friend/DSakiko3.10/reference_audio/anon/reference_audio_and_text.json"),
    dsakiko_root=Path("J:/AI friend/DSakiko3.10"),
)
payload = {
    "reference_language": assets.reference_language,
    "emotion_refs": {
        key.value: value.model_dump() for key, value in assets.emotion_refs.items()
    },
}
```

该工具只读取指定 JSON，并按 DSakiko 的 `GPT_SoVITS` 工作目录解释相对路径；不会扫描、
启动或改写 DSakiko。DSakiko 的语言文件值 `3` 会明确映射为 GPT-SoVITS API 的
`all_ja`，不会错误回退到全局英文参考语言。还需由操作者显式填写与权重兼容的 `tts_model_profile`。运行时会从
当前 GPT-SoVITS 配置中验证该 profile，避免把不同版本权重静默套进错误配置。
例如 DSakiko 目录中命名为 `*_v2pp_*` 的角色权重应明确配对并使用
`tts_model_profile="v2ProPlus"`；启动前配置文件会验证该 profile 是否存在。
