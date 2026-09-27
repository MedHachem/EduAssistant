/**
 * WebSocket frames exchanged with the AI Teacher (JSON, one frame per message).
 * This is the contract the backend is expected to implement.
 *
 * client → server
 *   user_message   the student asks something
 *   cancel         stop generating the answer to `replyTo`
 *
 * server → client
 *   assistant_start  a new answer begins (id of the assistant message + the user message it answers)
 *   assistant_delta  a chunk of text to append
 *   assistant_end    the answer is complete
 *   error            something failed (optionally tied to a message)
 */

export interface UserMessageFrame {
  type: 'user_message';
  conversationId: string;
  messageId: string;
  content: string;
}

export interface CancelFrame {
  type: 'cancel';
  conversationId: string;
  replyTo: string;
}

export type ClientFrame = UserMessageFrame | CancelFrame;

export interface AssistantStartFrame {
  type: 'assistant_start';
  conversationId: string;
  messageId: string;
  replyTo: string;
}

export interface AssistantDeltaFrame {
  type: 'assistant_delta';
  conversationId: string;
  messageId: string;
  delta: string;
}

export interface AssistantEndFrame {
  type: 'assistant_end';
  conversationId: string;
  messageId: string;
}

export interface ErrorFrame {
  type: 'error';
  conversationId?: string;
  /** User or assistant message the error relates to, if any. */
  messageId?: string;
  message: string;
}

export type ServerFrame = AssistantStartFrame | AssistantDeltaFrame | AssistantEndFrame | ErrorFrame;
