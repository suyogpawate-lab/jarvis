use ptts::checkpoint::{Checkpoint, ResolveOptions};
use ptts::preprocess::Lang;
use ptts::synth::{DeviceKind, Quant, SpeechOptions};
use serde::Deserialize;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;

#[derive(Deserialize)]
struct Request {
    text: String,
    output: String,
    voice: Option<String>,
}

fn respond(value: serde_json::Value) -> io::Result<()> {
    let stdout = io::stdout();
    let mut out = stdout.lock();
    serde_json::to_writer(&mut out, &value)?;
    out.write_all(b"\n")?;
    out.flush()
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
            if selected_voice != "default" && !available.iter().any(|name| name == selected_voice) {
                return Err(format!(
                    "voice '{}' is not registered; available voices: {}",
                    selected_voice,
                    available.join(", ")
                ).into());
            }
            let options = SpeechOptions::default().voice(selected_voice.to_string());
            let pcm = tts.say_with(&request.text, &options)?;
            ptts::wav::write_wav_file(&request.output, &pcm, tts.sample_rate())?;
            respond(serde_json::json!({"ok": true}))
                .map_err(|error| -> Box<dyn std::error::Error> { Box::new(error) })?;
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
