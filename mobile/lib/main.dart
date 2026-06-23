import 'dart:io';
import 'package:dio/dio.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';

void main() {
  runApp(const MyPrivacyApp());
}

class MyPrivacyApp extends StatelessWidget {
  const MyPrivacyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'My Privacy',
      theme: ThemeData(
        primarySwatch: Colors.deepPurple,
        useMaterial3: true,
      ),
      home: const VideoManagerScreen(),
    );
  }
}

enum AppState { idle, uploading, finishedUploading, downloading, downloadComplete }

class VideoManagerScreen extends StatefulWidget {
  const VideoManagerScreen({super.key});

  @override
  State<VideoManagerScreen> createState() => _VideoManagerScreenState();
}

class _VideoManagerScreenState extends State<VideoManagerScreen> {
  AppState _currentState = AppState.idle;
  double _progress = 0.0;
  String? _selectedFilePath;
  String? _downloadedFilePath;
  final Dio _dio = Dio();

  // 1. Local Storage Access
  Future<void> _selectVideo() async {
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.video,
        allowMultiple: false,
      );

      if (result != null && result.files.single.path != null) {
        setState(() {
          _selectedFilePath = result.files.single.path;
          _currentState = AppState.idle;
          _progress = 0.0;
        });
      }
    } catch (e) {
      _showError('Failed to pick video: $e');
    }
  }

  // 4. Permissions handling
  Future<bool> _requestPermissions() async {
    if (Platform.isAndroid) {
      final status = await Permission.storage.request();
      if (status.isGranted) return true;
      
      // For Android 13+ 
      final videoStatus = await Permission.videos.request();
      return videoStatus.isGranted;
    }
    return true; // iOS handles this differently via Info.plist
  }

  // 2. Upload Implementation
  Future<void> _uploadVideo() async {
    if (_selectedFilePath == null) return;

    if (!await _requestPermissions()) {
      _showError('Storage permission denied');
      return;
    }

    setState(() {
      _currentState = AppState.uploading;
      _progress = 0.0;
    });

    try {
      final file = File(_selectedFilePath!);
      final fileName = file.path.split('/').last;
      final formData = FormData.fromMap({
        'file': await MultipartFile.fromFile(file.path, filename: fileName),
      });

      await _dio.post(
        'https://api.example.com/upload', // Placeholder URL
        data: formData,
        onSendProgress: (sent, total) {
          setState(() {
            _progress = sent / total;
          });
        },
      );

      setState(() {
        _currentState = AppState.finishedUploading;
      });
    } catch (e) {
      setState(() => _currentState = AppState.idle);
      _showError('Upload failed: $e');
    }
  }

  // 3. Download Implementation
  Future<void> _downloadVideo() async {
    if (!await _requestPermissions()) {
      _showError('Storage permission denied');
      return;
    }

    setState(() {
      _currentState = AppState.downloading;
      _progress = 0.0;
    });

    try {
      final directory = await getExternalStorageDirectory(); // Or use Downloads path on Android
      final savePath = '${directory?.path}/downloaded_video.mp4';

      await _dio.download(
        'https://api.example.com/download/placeholder', // Placeholder URL
        savePath,
        onReceiveProgress: (received, total) {
          if (total != -1) {
            setState(() {
              _progress = received / total;
            });
          }
        },
      );

      setState(() {
        _downloadedFilePath = savePath;
        _currentState = AppState.downloadComplete;
      });
    } catch (e) {
      setState(() => _currentState = AppState.idle);
      _showError('Download failed: $e');
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My Privacy - Video Manager')),
      body: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text('Status: ${_currentState.name.toUpperCase()}', 
              style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
            const SizedBox(height: 20),
            if (_currentState == AppState.uploading || _currentState == AppState.downloading) ...[
              LinearProgressIndicator(value: _progress),
              const SizedBox(height: 10),
              Text('${(_progress * 100).toStringAsFixed(0)}%'),
            ],
            const SizedBox(height: 30),
            if (_selectedFilePath != null) 
              Text('Selected: ${_selectedFilePath!.split('/').last}'),
            const SizedBox(height: 20),
            Wrap(
              spacing: 10,
              children: [
                ElevatedButton(
                  onPressed: _currentState == AppState.uploading || _currentState == AppState.downloading 
                    ? null : _selectVideo,
                  child: const Text('Select Video'),
                ),
                ElevatedButton(
                  onPressed: _selectedFilePath != null && _currentState == AppState.idle 
                    ? _uploadVideo : null,
                  child: const Text('Upload'),
                ),
                ElevatedButton(
                  onPressed: _currentState == AppState.finishedUploading || _currentState == AppState.downloadComplete
                    ? _downloadVideo : null,
                  child: const Text('Download'),
                ),
              ],
            ),
            if (_currentState == AppState.downloadComplete) ...[
              const SizedBox(height: 20),
              const Text('✅ Downloaded successfully!', style: TextStyle(color: Colors.green)),
              Text('Saved to: $_downloadedFilePath', style: const TextStyle(fontSize: 12)),
            ]
          ],
        ),
      ),
    );
  }
}
