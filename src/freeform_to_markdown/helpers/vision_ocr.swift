#!/usr/bin/env swift

import AppKit
import CoreGraphics
import Foundation
import PDFKit
import Vision

struct PageResult: Codable {
    let page: Int
    let text: String
}

struct Success: Codable {
    let ok: Bool
    let pages: [PageResult]
    let warnings: [String]
}

struct Failure: Codable {
    let ok: Bool
    let error: String
}

enum HelperError: Error {
    case invalidArguments
    case unreadableInput
    case unsupportedInput
    case renderFailed
}

func emit<T: Encodable>(_ value: T) {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    guard let data = try? encoder.encode(value), let text = String(data: data, encoding: .utf8) else {
        print("{\"error\":\"JSON encoding failed\",\"ok\":false}")
        return
    }
    print(text)
}

func recognize(_ image: CGImage) throws -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    try handler.perform([request])
    return (request.results ?? [])
        .compactMap { $0.topCandidates(1).first?.string }
        .joined(separator: "\n")
}

func cgImage(from page: PDFPage) throws -> CGImage {
    let bounds = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.0
    let width = max(1, Int(ceil(bounds.width * scale)))
    let height = max(1, Int(ceil(bounds.height * scale)))
    guard let context = CGContext(
        data: nil,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        throw HelperError.renderFailed
    }
    context.setFillColor(CGColor(gray: 1.0, alpha: 1.0))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.saveGState()
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    context.restoreGState()
    guard let image = context.makeImage() else { throw HelperError.renderFailed }
    return image
}

func requestedPages(_ arguments: [String]) throws -> Set<Int>? {
    guard let marker = arguments.firstIndex(of: "--pages") else { return nil }
    guard marker + 1 < arguments.count else { throw HelperError.invalidArguments }
    let pages = arguments[marker + 1]
        .split(separator: ",")
        .compactMap { Int($0) }
        .filter { $0 > 0 }
    guard !pages.isEmpty else { throw HelperError.invalidArguments }
    return Set(pages)
}

func run() throws -> Success {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard let rawPath = arguments.first else { throw HelperError.invalidArguments }
    let input = URL(fileURLWithPath: rawPath)
    let selected = try requestedPages(arguments)
    if input.pathExtension.lowercased() == "pdf" {
        guard let document = PDFDocument(url: input) else { throw HelperError.unreadableInput }
        var results: [PageResult] = []
        var warnings: [String] = []
        for index in 0..<document.pageCount {
            let pageNumber = index + 1
            if let selected, !selected.contains(pageNumber) { continue }
            guard let page = document.page(at: index) else {
                warnings.append("PDF page \(pageNumber) could not be loaded")
                continue
            }
            let text = try recognize(cgImage(from: page))
            results.append(PageResult(page: pageNumber, text: text))
        }
        return Success(ok: true, pages: results, warnings: warnings)
    }
    guard let source = NSImage(contentsOf: input) else { throw HelperError.unreadableInput }
    var proposed = CGRect(origin: .zero, size: source.size)
    guard let image = source.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else {
        throw HelperError.renderFailed
    }
    return Success(
        ok: true,
        pages: [PageResult(page: 1, text: try recognize(image))],
        warnings: []
    )
}

do {
    emit(try run())
} catch HelperError.invalidArguments {
    emit(Failure(ok: false, error: "invalid arguments"))
    exit(2)
} catch HelperError.unreadableInput {
    emit(Failure(ok: false, error: "input could not be decoded"))
    exit(3)
} catch HelperError.unsupportedInput {
    emit(Failure(ok: false, error: "unsupported input"))
    exit(4)
} catch {
    emit(Failure(ok: false, error: "local OCR failed"))
    exit(5)
}
