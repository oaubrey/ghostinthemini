"""Application entry point."""
import ollama

from ghostinthemini.config import MODEL


def main() -> None:
    """Run the application."""
    print("Boo! 👻")


def ghost_pulse_check():
    print("👻 GhostInTheMini: Initializing pulse check...")

    try:
        # This sends a simple message to your local model
        response = ollama.chat(model=MODEL, messages=[
            {
                'role': 'system',
                'content': (
                    f'You are the {MODEL} model installed and running '
                    'locally on the M4 Mac Mini via Ollama. You are a helpful '
                    'assistant that is used to help schedule tasks and events '
                    'for the user.'
                ),
            },
            {
                'role': 'user',
                'content': 'System check: Is the ghost in the mini awake?',
            },
        ])
        
        # Print the response from the model
        print("\n--- Ghost Response ---")
        print(response['message']['content'])
        print("----------------------\n")
        print("✅ Connection Successful: The Ghost is awake.")

    except Exception as e:
        print(f"❌ Error: Could not connect to the Ghost. Make sure Ollama is running!")
        print(f"Details: {e}")

if __name__ == "__main__":
    ghost_pulse_check()
