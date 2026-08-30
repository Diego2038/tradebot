import 'package:flutter/material.dart';

import 'services/api_client.dart';

void main() {
  runApp(const TradeBotApp());
}

class TradeBotApp extends StatelessWidget {
  const TradeBotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'TradeBot',
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: const HomeScreen(),
    );
  }
}

/// Pantalla inicial de esqueleto.
///
/// En el spec 08-web-frontend se ampliará con:
///  - Pantalla de configuración de la API Key de Alpaca (se envía al backend,
///    que la cifra antes de guardarla).
///  - Selección de modo del bot (random / predictive).
///  - Dashboard con el feed en tiempo real (WebSocket) de las acciones del bot.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _api = ApiClient();
  String _status = 'Sin verificar';

  Future<void> _checkBackend() async {
    setState(() => _status = 'Verificando...');
    try {
      final data = await _api.health();
      setState(() => _status = 'Backend OK · modo: ${data['mode']}');
    } catch (e) {
      setState(() => _status = 'Error: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('TradeBot · Paper Trading')),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('TradeBot', style: TextStyle(fontSize: 28)),
            const SizedBox(height: 8),
            Text(_status),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _checkBackend,
              child: const Text('Probar conexión con el backend'),
            ),
          ],
        ),
      ),
    );
  }
}
