from src.lib.Models import OpenAITTSModel, create_tts_model


def local_tts_config() -> dict:
    return {
        "api_key": "local",
        "tts_api_key": "local",
        "tts_chatterbox_endpoint": "http://speech-box:8004/v1",
        "tts_qwen3_endpoint": "http://speech-box:8005/v1",
        "tts_language": "fr",
        "tts_append_language_to_model": True,
        "tts_speed": 1.2,
        "tts_voice_instructions": "Parlez avec un accent français naturel.",
    }


def test_chatterbox_local_profile_builds_language_model_name() -> None:
    model = create_tts_model("chatterbox-local", local_tts_config())

    assert isinstance(model, OpenAITTSModel)
    assert str(model.client.base_url) == "http://speech-box:8004/v1/"
    assert model.model_name == "chatterbox-fr"
    assert model.voice_instructions == "Parlez avec un accent français naturel."


def test_qwen_local_profile_can_disable_language_suffix() -> None:
    config = local_tts_config()
    config["tts_append_language_to_model"] = False

    model = create_tts_model("qwen3-tts-local", config)

    assert isinstance(model, OpenAITTSModel)
    assert str(model.client.base_url) == "http://speech-box:8005/v1/"
    assert model.model_name == "qwen3-tts"
