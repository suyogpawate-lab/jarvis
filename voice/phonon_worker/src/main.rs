use ptts::checkpoint::{Checkpoint, ResolveOptions};
use ptts::preprocess::Lang;
use ptts::synth::{DeviceKind, Quant, SpeechOptions};
use serde::Deserialize;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;

#[derive(Deserialize)]
struct Request {
    text: String,
    output: Option<String>,
    voice: Option<String>,
    #[serde(default)]
    stream: bool,
}

fn respond(value: serde_json::Value) -> io::Result<()> {
    let stdout = io::stdout();
    let mut out = stdout.lock();
    serde_json::to_writer(&mut out, &value)?;
    out.write_all(b"\n")?;
    out.flush()
}

// Encode PCM bytes without adding another dependency to the Android worker.
fn base64_encode(data: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = Vec::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let a = chunk[0] as u32;
        let b = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let c = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        out.push(TABLE[(a >> 2) as usize]);
        out.push(TABLE[(((a & 0x03) << 4) | (b >> 4)) as usize]);
        out.push(if chunk.len() > 1 { TABLE[(((b & 0x0f) << 2) | (c >> 6)) as usize] } else { b'=' });
        out.push(if chunk.len() > 2 { TABLE[(c & 0x3f) as usize] } else { b'=' });
    }
    String::from_utf8(out).expect("base64 output is ASCII")
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let model = args.next().ok_or("usage: jarvis-phonon-worker MODEL VOICE QUANT")?;
    let voice = args.next().ok_or("missing voice")?;
    let quant_name = args.next().ok_or("missing quantization")?;
    let quant = quant_name.parse::<Quant>()?;
    let checkpoint = Checkpoint::resolve(
        PathBuf::from(model),
        ResolveOptions { quant, weights: None },
    )?;
    let mut tts = checkpoint.builder(Lang::En).device(DeviceKind::Cpu).build()?;
    checkpoint.register_voices(&mut tts);
    let available = tts.voices();
    if voice != "default" && !available.iter().any(|name| name == &voice) {
        return Err(format!("voice '{voice}' is not registered; available voices: {}", available.join(", ")).into());
    }
    eprintln!("[JARVIS Phonon] Model loaded once; persistent worker ready.");
    respond(serde_json::json!({"ready": true, "voices": available.clone()}))?;

    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        let result = (|| -> Result<(), Box<dyn std::error::Error>> {
            let request: Request = serde_json::from_str(&line)?;
            let selected_voice = request.voice.as_deref().unwrap_or(voice.as_str());
            if selected_voice != "default" && !available.iter().any(|name| name.as_str() == selected_voice) {
                return Err(format!(
                    "voice '{}' is not registered; available voices: {}",
                    selected_voice,
                    available.join(", ")
                ).into());
            }
            let options = SpeechOptions::default().voice(selected_voice.to_string());
            if request.stream {
                let sample_rate = tts.sample_rate();
                let stream = tts.stream_with(&request.text, &options)?;
                respond(serde_json::json!({"stream": true, "sample_rate": sample_rate}))?;
                for chunk in stream {
                    match chunk {
                        Ok(samples) => {
                            let mut bytes = Vec::with_capacity(samples.len() * 4);
                            for sample in samples {
                                bytes.extend_from_slice(&sample.to_le_bytes());
                            }
                            respond(serde_json::json!({"chunk": base64_encode(&bytes)}))?;
                        }
                        Err(error) => {
                            respond(serde_json::json!({"ok": false, "error": error.to_string()}))?;
                            return Ok(());
                        }
                    }
                }
                respond(serde_json::json!({"done": true}))?;
            } else {
                let output = request.output.as_deref().ok_or("output path is required for WAV mode")?;
                let pcm = tts.say_with(&request.text, &options)?;
                ptts::wav::write_wav_file(output, &pcm, tts.sample_rate())?;
                respond(serde_json::json!({"ok": true}))
                    .map_err(|error| -> Box<dyn std::error::Error> { Box::new(error) })?;
            }
            Ok(())
        })();
        if let Err(error) = result {
            let _ = respond(serde_json::json!({"ok": false, "error": error.to_string()}));
        }
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("[JARVIS Phonon] Worker failed: {error:#}");
        std::process::exit(1);
    }
}
