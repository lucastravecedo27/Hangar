import Foundation
import Vision
import AppKit
// Uso: ocr <imagen>...  -> por cada imagen, líneas "x y w h|texto" (normalizadas, origen arriba-izquierda)
for ruta in CommandLine.arguments.dropFirst() {
  let url = URL(fileURLWithPath: ruta)
  guard let img = NSImage(contentsOf: url), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
  let req = VNRecognizeTextRequest()
  req.recognitionLevel = .accurate
  req.usesLanguageCorrection = false
  req.recognitionLanguages = ["en-US"]
  try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
  print("### " + ruta)
  for o in (req.results ?? []) {
    guard let t = o.topCandidates(1).first else { continue }
    let b = o.boundingBox
    print(String(format: "%.4f %.4f %.4f %.4f|", b.minX, 1 - b.maxY, b.width, b.height) + t.string)
  }
}
