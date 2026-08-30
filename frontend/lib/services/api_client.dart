import 'dart:convert';
import 'package:http/http.dart' as http;

/// Cliente REST hacia el backend de TradeBot.
///
/// La URL base se toma de --dart-define=API_BASE_URL, con un default de desarrollo.
class ApiClient {
  ApiClient({String? baseUrl})
      : baseUrl = baseUrl ??
            const String.fromEnvironment(
              'API_BASE_URL',
              defaultValue: 'http://localhost:8000',
            );

  final String baseUrl;

  Future<Map<String, dynamic>> health() async {
    final res = await http.get(Uri.parse('$baseUrl/health'));
    if (res.statusCode != 200) {
      throw Exception('Health check falló: ${res.statusCode}');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  // TODO(07-bot-api): guardar credenciales de Alpaca (cifradas en backend),
  // arrancar/detener el bot, seleccionar modo (random/predictive), consultar estado.
}
