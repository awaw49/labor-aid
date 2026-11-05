// 使用 macOS Vision 框架做中文 OCR，输出逐行文本与置信度（JSON）
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1 else { print("{\"error\":\"usage: vision_ocr <image>\"}"); exit(1) }
let url = URL(fileURLWithPath: args[1])
guard let img = NSImage(contentsOf: url), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("{\"error\":\"cannot load image\"}"); exit(1)
}
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do { try handler.perform([request]) } catch { print("{\"error\":\"ocr failed\"}"); exit(1) }
var lines: [[String: Any]] = []
if let obs = request.results as? [VNRecognizedTextObservation] {
    for o in obs {
        if let top = o.topCandidates(1).first {
            lines.append(["text": top.string, "conf": Double(top.confidence),
                          "y": Double(o.boundingBox.origin.y), "x": Double(o.boundingBox.origin.x)])
        }
    }
}
let data = try JSONSerialization.data(withJSONObject: ["lines": lines], options: [])
FileHandle.standardOutput.write(data)
