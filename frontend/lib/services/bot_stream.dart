import 'package:web_socket_channel/web_socket_channel.dart';

/// Suscripción al feed en tiempo real de acciones del bot (WebSocket).
///
/// El backend (spec 07-bot-api) publica eventos: señales, órdenes, fills,
/// cambios de estado y errores. El dashboard (spec 08) los renderiza en vivo.
class BotStream {
  BotStream({String? wsUrl})
      : wsUrl = wsUrl ??
            const String.fromEnvironment(
              'WS_BASE_URL',
              defaultValue: 'ws://localhost:8000/ws/bot',
            );

  final String wsUrl;
  WebSocketChannel? _channel;

  Stream<dynamic> connect() {
    _channel = WebSocketChannel.connect(Uri.parse(wsUrl));
    return _channel!.stream;
  }

  void dispose() {
    _channel?.sink.close();
  }
}
