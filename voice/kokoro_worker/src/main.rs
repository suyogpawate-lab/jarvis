use kokoro_en::{KokoroTts, Voice};
use serde::Deserialize;
use std::{
    io::{self, BufRead, Write},
    path::PathBuf,
};

#[derive(Deserialize)]
struct Request {
    text: String,
    voice: String,
    #[serde(default = "default_speed")]
    speed: f32,
    output: String,
}

fn default_speed() -> f32 { 1.0 }

fn respond(value: serde_json::Value) -> io::Result<()> {
    let stdout = io::stdout();
    let mut out = stdout.lock();
    serde_json::to_writer(&mut out, &value)?;
    out.write_all(b"\n")?;
    out.flush()
}

fn write_wav(path: &str, samples: &[f32], sample_rate: u32) -> Result<(), Box<dyn std::error::Error>> {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec)?;
    for sample in samples {
        let pcm = (sample.clamp(-1.0, 1.0) * i16::MAX as f32).round() as i16;
        writer.write_sample(pcm)?;
    }
    writer.finalize()?;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let model = PathBuf::from(args.next().ok_or("usage: jarvis-kokoro-worker MODEL VOICES_DIR")?);
    let voices = PathBuf::from(args.next().ok_or("missing voices directory")?);
    eprintln!("[JARVIS Kokoro] Loading Kokoro-82M ONNX and voice packs...");
    let tts = KokoroTts::new(&model, &voices).await?;
    let available = tts.voices();
    if available.len() < 54 {
        return Err(format!("Expected all 54 Kokoro voices, loaded {}: {}", available.len(), available.join(", ")).into());
    }
    let sample_rate = tts.sample_rate();
    // Real synthesis warmup: the model is ready before the service advertises itself.
    let (_warm_audio, warm_elapsed) = tts.synth("Ready.", "am_onyx").await?;
    eprintln!("[JARVIS Kokoro] Model loaded; {} voices resident; warmup {:?}.", available.len(), warm_elapsed);
    respond(serde_json::json!({
        "ready": true,
        "model": "Kokoro-82M-v1.0-ONNX-q8f16",
        "voices_loaded": available.len(),
        "voices": available,
        "sample_rate": sample_rate,
        "warmup_ms": warm_elapsed.as_millis()
    }))?;

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() { continue; }
        let result = (|| -> Result<(), Box<dyn std::error::Error>> {
            let request: Request = serde_json::from_str(&line)?;
            if request.text.trim().is_empty() { return Err("text is empty".into()); }
            if !request.speed.is_finite() || !(0.5..=2.0).contains(&request.speed) {
                return Err("speed must be between 0.5 and 2.0".into());
            }
            if !available.iter().any(|name| name == &request.voice) {
                return Err(format!("unknown voice '{}'", request.voice).into());
            }
            Ok((request.text, request.voice, request.speed, request.output))
        })();
        match result {
            Ok((text, voice, speed, output)) => {
                match tts.synth(&text, Voice::new(voice).with_speed(speed)).await {
                    Ok((audio, elapsed)) if !audio.is_empty() => {
                        if let Err(error) = write_wav(&output, &audio, sample_rate) {
                            let _ = respond(serde_json::json!({"ok": false, "error": error.to_string()}));
                            continue;
                        }
                        respond(serde_json::json!({
                            "ok": true,
                            "synthesis_ms": elapsed.as_millis(),
                            "samples": audio.len(),
                            "sample_rate": sample_rate
                        }))?;
                    }
                    Ok(_) => {
                        respond(serde_json::json!({"ok": false, "error": "Kokoro returned empty audio"}))?;
                    }
                    Err(error) => {
                        respond(serde_json::json!({"ok": false, "error": error.to_string()}))?;
                    }
                }
            }
            Err(error) => {
                let _ = respond(serde_json::json!({"ok": false, "error": error.to_string()}));
            }
        }
    }
    Ok(())
}
