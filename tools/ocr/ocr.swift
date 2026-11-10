// macOS Vision 문자 인식 CLI — 이미지 경로들을 받아 한 줄에 JSON 하나씩 출력한다.
//   ./ocr <img> [<img> ...]   →  {"file":..., "w":..., "h":..., "lines":[{"text":..., "conf":..., "x":..., "y":..., "w":..., "h":...}]}
// 좌표는 픽셀(왼쪽 위 원점). 언어 ko-KR + en-US, 정확도 우선.
import Foundation
import Vision
import AppKit

func ocr(_ path: String) -> [String: Any]? {
    guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
    let W = Double(cg.width), H = Double(cg.height)
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["ko-KR", "en-US"]
    req.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch { return nil }
    var lines: [[String: Any]] = []
    for obs in (req.results ?? []) {
        guard let top = obs.topCandidates(1).first else { continue }
        let b = obs.boundingBox
        lines.append(["text": top.string, "conf": Double(top.confidence),
                      "x": Int(b.minX * W), "y": Int((1 - b.maxY) * H), "w": Int(b.width * W), "h": Int(b.height * H)])
    }
    return ["file": path, "w": Int(W), "h": Int(H), "lines": lines]
}

for p in CommandLine.arguments.dropFirst() {
    if let r = ocr(p), let d = try? JSONSerialization.data(withJSONObject: r, options: []), let s = String(data: d, encoding: .utf8) {
        print(s)
    } else {
        print("{\"file\": \"\(p)\", \"error\": true}")
    }
}
