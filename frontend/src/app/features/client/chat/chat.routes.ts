import { Routes } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { ChatPage } from './chat-page';
import { ChatStore } from './chat.store';
import { ChatTransport } from './transport/chat-transport';
import { MockChatTransport } from './transport/mock-chat-transport';
import { WebSocketChatTransport } from './transport/websocket-chat-transport';

export const chatRoutes: Routes = [
  {
    path: '',
    component: ChatPage,
    // Route-level providers: the connection and conversations survive navigating away and back.
    providers: [
      { provide: ChatTransport, useClass: environment.chat.mock ? MockChatTransport : WebSocketChatTransport },
      ChatStore,
    ],
  },
];
