export type Role = 'user' | 'assistant';

export type MessageStatus =
  | 'pending' // user message queued (socket not connected yet)
  | 'sent' // user message handed to the socket
  | 'streaming' // assistant message receiving deltas
  | 'done'
  | 'cancelled'
  | 'error';

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  createdAt: string;
  status: MessageStatus;
  /** Assistant messages: id of the user message being answered. */
  replyTo?: string;
  error?: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export type ConnectionStatus = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'offline';
