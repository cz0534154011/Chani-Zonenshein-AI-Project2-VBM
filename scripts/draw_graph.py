"""Print the main graph, with the negotiation subgraph inside it, as a Mermaid diagram for the README (no model calls, no network)."""

from vbm.infrastructure.workflow.graph import graph


# הדפסת תרשים הגרף הראשי, כולל תת-הגרף, כבלוק Mermaid להעתקה ל-README
def main() -> None:
    """Draw the compiled graph with xray=True and print it as a Mermaid block."""
    print("```mermaid")
    print(graph.get_graph(xray=True).draw_mermaid().strip())
    print("```")


if __name__ == "__main__":
    main()
