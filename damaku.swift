// 1. 数据模型层 Models/BiliModels.swift
import Foundation

struct BiliCredential {
    let sessdata: String
    let biliJct: String
    let buvid3: String
}

struct VideoPart: Identifiable, Decodable {
    let id = UUID()
    let cid: Int
    let part: String
    let page: Int
    
    enum CodingKeys: String, CodingKey {
        case cid, part, page
    }
}

struct Danmaku: Decodable {
    let time: String
    let mode: String
    let content: String
}

// 2. 网络服务层 Services/BiliAPIManager.swift
import Combine

class BiliAPIManager {
    static let shared = BiliAPIManager()
    private let session = URLSession.shared
    
    private init() {}
    
    func fetchVideoParts(bvid: String, credential: BiliCredential) -> AnyPublisher<[VideoPart], Error> {
        var components = URLComponents(string: "https://api.bilibili.com/x/web-interface/view")!
        components.queryItems = [URLQueryItem(name: "bvid", value: bvid)]
        
        var request = URLRequest(url: components.url!)
        request.addValue("SESSDATA=\(credential.sessdata); bili_jct=\(credential.biliJct); buvid3=\(credential.buvid3)", 
                       forHTTPHeaderField: "Cookie")
        
        return session.dataTaskPublisher(for: request)
            .tryMap { output in
                let decoder = JSONDecoder()
                let response = try decoder.decode(BiliAPIResponse.self, from: output.data)
                return response.data.pages
            }
            .eraseToAnyPublisher()
    }
    
    func sendDanmaku(cid: Int, danmaku: Danmaku, credential: BiliCredential) -> AnyPublisher<Bool, Error> {
        var components = URLComponents(string: "https://api.bilibili.com/x/v2/dm/post")!
        components.queryItems = [
            URLQueryItem(name: "oid", value: String(cid)),
            URLQueryItem(name: "type", value: "1"),
            URLQueryItem(name: "mode", value: danmaku.mode),
            URLQueryItem(name: "message", value: danmaku.content),
            URLQueryItem(name: "csrf", value: credential.biliJct)
        ]
        
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.addValue("SESSDATA=\(credential.sessdata)", forHTTPHeaderField: "Cookie")
        
        return session.dataTaskPublisher(for: request)
            .tryMap { output in
                let response = try JSONDecoder().decode(BiliBaseResponse.self, from: output.data)
                return response.code == 0
            }
            .eraseToAnyPublisher()
    }
}

private struct BiliAPIResponse: Decodable {
    let code: Int
    let data: BiliVideoData
}

private struct BiliVideoData: Decodable {
    let pages: [VideoPart]
}

private struct BiliBaseResponse: Decodable {
    let code: Int
    let message: String
}

// 3. 视图模型层 ViewModels/DanmakuViewModel.swift
import Combine
import SwiftUI

class DanmakuViewModel: ObservableObject {
    @Published var bvid = ""
    @Published var selectedPart: VideoPart?
    @Published var progress: CGFloat = 0
    @Published var isProcessing = false
    @Published var showAlert = false
    @Published var alertMessage = ""
    
    private var cancellables = Set<AnyCancellable>()
    
    func loadVideoParts(credential: BiliCredential) {
        guard !bvid.isEmpty else { return }
        
        isProcessing = true
        BiliAPIManager.shared.fetchVideoParts(bvid: bvid, credential: credential)
            .receive(on: DispatchQueue.main)
            .sink(receiveCompletion: { [weak self] completion in
                self?.isProcessing = false
                if case .failure(let error) = completion {
                    self?.showAlert(message: "加载失败: \(error.localizedDescription)")
                }
            }, receiveValue: { [weak self] parts in
                self?.handleParts(parts)
            })
            .store(in: &cancellables)
    }
    
    func sendDanmakuList(_ list: [Danmaku], credential: BiliCredential) {
        guard let cid = selectedPart?.cid else { return }
        
        isProcessing = true
        let total = list.count
        var successCount = 0
        
        list.publisher
            .flatMap(maxPublishers: .max(1)) { dm in
                BiliAPIManager.shared.sendDanmaku(cid: cid, danmaku: dm, credential: credential)
                    .delay(for: .seconds(20 + Double.random(in: 0...5)), scheduler: DispatchQueue.global())
            }
            .receive(on: DispatchQueue.main)
            .sink(receiveCompletion: { [weak self] _ in
                self?.isProcessing = false
                self?.showAlert(message: "发送完成 成功: \(successCount)/\(total)")
            }, receiveValue: { [weak self] success in
                if success {
                    successCount += 1
                }
                self?.progress = CGFloat(successCount) / CGFloat(total)
            })
            .store(in: &cancellables)
    }
    
    private func handleParts(_ parts: [VideoPart]) {
        // 处理分P选择逻辑
    }
    
    private func showAlert(message: String) {
        alertMessage = message
        showAlert = true
    }
}

// 4. UI组件层 Components/DanmakuFilePicker.swift
import SwiftUI

struct DanmakuFilePicker: UIViewControllerRepresentable {
    @Binding var fileContent: String?
    
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.xml])
        picker.allowsMultipleSelection = false
        picker.delegate = context.coordinator
        return picker
    }
    
    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, UIDocumentPickerDelegate {
        var parent: DanmakuFilePicker
        
        init(_ parent: DanmakuFilePicker) {
            self.parent = parent
        }
        
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            do {
                parent.fileContent = try String(contentsOf: url)
            } catch {
                print("文件读取失败: \(error)")
            }
        }
    }
}

// 5. 主界面层 Views/ContentScreen.swift
import SwiftUI

struct ContentScreen: View {
    @StateObject private var viewModel = DanmakuViewModel()
    @State private var credential = BiliCredential(sessdata: "", biliJct: "", buvid3: "")
    @State private var showCredentialSheet = false
    @State private var xmlContent: String?
    
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                credentialSection
                mainControls
                progressSection
            }
            .padding()
            .navigationTitle("B站弹幕工具")
            .toolbar { settingsToolbar }
            .alert("提示", isPresented: $viewModel.showAlert) {
                Button("确定") {}
            } message: {
                Text(viewModel.alertMessage)
            }
        }
    }
    
    private var credentialSection: some View {
        Section {
            TextField("SESSDATA", text: $credential.sessdata)
                .textFieldStyle(.roundedBorder)
            TextField("bili_jct", text: $credential.biliJct)
                .textFieldStyle(.roundedBorder)
            TextField("buvid3", text: $credential.buvid3)
                .textFieldStyle(.roundedBorder)
        } header: {
            Text("认证信息")
        }
    }
    
    private var mainControls: some View {
        Group {
            TextField("输入BV号", text: $viewModel.bvid)
                .textFieldStyle(.roundedBorder)
                .onSubmit {
                    viewModel.loadVideoParts(credential: credential)
                }
            
            DanmakuFilePicker(fileContent: $xmlContent)
                .buttonStyle(.borderedProminent)
            
            if let selectedPart = viewModel.selectedPart {
                Text("已选分P: P\(selectedPart.page) - \(selectedPart.part)")
            }
            
            Button(action: startSending) {
                Label("开始发送", systemImage: "paperplane")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canStartSending)
        }
    }
    
    private var progressSection: some View {
        Group {
            if viewModel.isProcessing {
                ProgressView(value: viewModel.progress)
                    .progressViewStyle(.linear)
                Text("已发送: \(Int(viewModel.progress * 100))%")
            }
        }
    }
    
    private var settingsToolbar: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Button("设置") {
                showCredentialSheet.toggle()
            }
        }
    }
    
    private var canStartSending: Bool {
        !credential.sessdata.isEmpty &&
        !credential.biliJct.isEmpty &&
        !viewModel.bvid.isEmpty &&
        xmlContent != nil
    }
    
    private func startSending() {
        guard let xmlData = xmlContent?.data(using: .utf8) else { return }
        
        do {
            let parser = DanmakuXMLParser()
            let danmakuList = try parser.parse(xmlData)
            viewModel.sendDanmakuList(danmakuList, credential: credential)
        } catch {
            viewModel.showAlert(message: "解析失败: \(error.localizedDescription)")
        }
    }
}

// 6. XML解析器 Services/DanmakuXMLParser.swift
import Foundation

class DanmakuXMLParser {
    func parse(_ data: Data) throws -> [Danmaku] {
        let parser = XMLParser(data: data)
        let delegate = ParserDelegate()
        parser.delegate = delegate
        if parser.parse() {
            return delegate.result
        } else {
            throw NSError(domain: "XMLParserError", code: -1, userInfo: nil)
        }
    }
    
    private class ParserDelegate: NSObject, XMLParserDelegate {
        var result: [Danmaku] = []
        
        func parser(_ parser: XMLParser, didStartElement elementName: String, 
                   namespaceURI: String?, qualifiedName qName: String?, 
                   attributes attributeDict: [String : String] = [:]) {
            guard elementName == "d", let p = attributeDict["p"] else { return }
            let components = p.components(separatedBy: ",")
            guard components.count >= 4 else { return }
            
            if let text = attributeDict["text"] {
                result.append(Danmaku(
                    time: components[0],
                    mode: components[1],
                    content: text
                ))
            }
        }
    }
}

// 7. 预览组件
#Preview {
    ContentScreen()
}
