from constants import MAGIC_COOKIE, PAYLOAD_TYPE, UDP_PORT
import socket
import struct


def client_main(team_name="Team_Joker"):
    team_name = team_name
    while True:
        num_rounds = int(input("How many rounds to play? "))
        print("Client started, listening for offer requests...")

        # Listen for UDP offer
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_sock.bind(("", UDP_PORT))

        # Receive Offer
        data, addr = udp_sock.recvfrom(1024)
        cookie, mtype, tcp_port, s_name = struct.unpack("!IBH32s", data)

        # Validate Offer
        if cookie != MAGIC_COOKIE: continue
        print(f"Received offer from {addr[0]}")
        udp_sock.close()

        # Connect via TCP
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.connect((addr[0], tcp_port))

        # Send Request
        req = struct.pack("!IBB32s", MAGIC_COOKIE, 0x3, num_rounds, team_name.encode().ljust(32, b'\x00'))
        tcp_sock.sendall(req)


        wins = 0
        # Set timeout for TCP socket
        tcp_sock.settimeout(5.0)
        # Play rounds
        for r in range(num_rounds):
            print(f"\n--- Round {r + 1} ---")
            player_hand = []

            # Receive initial 3 cards
            for _ in range(3):
                p_data = tcp_sock.recv(14)
                _, _, _, _, rank, suit = struct.unpack("!IB5sBHB", p_data)
                print(f"Card received: rank {rank}, suit {suit}")

            # Initialize round result
            current_result = 0x0

            # Player Turn
            while current_result == 0x0:
                # Ask player for decision
                choice = input("Hit or Stand? (h/s): ")
                decision = b"Hittt" if choice.lower() == 'h' else b"Stand"

                # Send player decision
                tcp_sock.sendall(struct.pack("!IB5sBHB", MAGIC_COOKIE, PAYLOAD_TYPE, decision, 0, 0, 0))

                # Wait for server response to our action
                p_data = tcp_sock.recv(14)
                _, _, _, res, rank, suit = struct.unpack("!IB5sBHB", p_data)

                if decision == b"Hittt" and current_result == 0:
                    print(f"New card received: {rank}")

                if decision == b"Stand":
                    break

            # If the player hasn't already lost, we must listen for Dealer's cards
            while current_result == 0:
                # Wait for dealer's action
                p_data = tcp_sock.recv(14)
                _, _, _, current_result, rank, suit = struct.unpack("!IB5sBHB", p_data)

                # Show dealer's revealed/drawn card
                if rank != 0:
                    print(f"Dealer reveals/draws: {rank}")


            # Display Final Round Result
            if current_result == 0x3:
                print(">>> RESULT: You won, now go do something with your life!")
                wins += 1
            elif current_result == 0x2:
                print(">>> RESULT: You lost, please dont play this game ever again!")
            elif current_result == 0x1:
                print(">>> RESULT: It's a butterfly tie!")

        win_rates = wins / num_rounds * 100 if num_rounds > 0 else 0
        print(f"\nFinished playing {num_rounds} rounds, win rate: {win_rates}%")
        tcp_sock.close()


if __name__ == "__main__":
    client_main(input("Enter your team name: "))
