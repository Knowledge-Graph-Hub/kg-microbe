#!/usr/bin/env python3
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import json

def load_data(nodes_file, edges_file):
    """Load nodes and edges from TSV files"""
    print("Loading nodes...")
    nodes_df = pd.read_csv(nodes_file, sep='\t', low_memory=False)
    
    print("Loading edges...")
    edges_df = pd.read_csv(edges_file, sep='\t', low_memory=False)
    
    return nodes_df, edges_df

def find_1hop_subgraph(nodes_df, edges_df, center_id):
    """Find 1-hop subgraph around center node"""
    
    # Find center node
    center_node = nodes_df[nodes_df['id'] == center_id]
    if center_node.empty:
        print(f"Center node {center_id} not found")
        return None, None
    
    # Get all edges involving the center node
    center_edges = edges_df[(edges_df['subject'] == center_id) | (edges_df['object'] == center_id)]
    
    # Get 1-hop neighbors
    hop1_ids = set()
    for _, edge in center_edges.iterrows():
        if edge['subject'] == center_id:
            hop1_ids.add(edge['object'])
        else:
            hop1_ids.add(edge['subject'])
    
    print(f"Found {len(hop1_ids)} 1-hop neighbors")
    
    # Get all relevant node IDs
    all_node_ids = {center_id} | hop1_ids
    
    # Get subgraph nodes
    subgraph_nodes = nodes_df[nodes_df['id'].isin(all_node_ids)].copy()
    
    # Add hop information
    subgraph_nodes.loc[subgraph_nodes['id'] == center_id, 'hop'] = 0
    subgraph_nodes.loc[subgraph_nodes['id'].isin(hop1_ids), 'hop'] = 1
    
    # Get subgraph edges (only direct connections to center)
    subgraph_edges = center_edges.copy()
    
    print(f"1-hop Subgraph: {len(subgraph_nodes)} nodes, {len(subgraph_edges)} edges")
    
    return subgraph_nodes, subgraph_edges

def create_1hop_visualization(nodes_df, edges_df, center_id, output_file):
    """Create 1-hop network visualization with comprehensive labels"""
    
    # Create NetworkX graph
    G = nx.Graph()
    
    # Add nodes
    for _, node in nodes_df.iterrows():
        G.add_node(node['id'], 
                  name=node['name'], 
                  category=node['category'], 
                  hop=node['hop'])
    
    # Add edges
    for _, edge in edges_df.iterrows():
        if edge['subject'] in G.nodes and edge['object'] in G.nodes:
            G.add_edge(edge['subject'], edge['object'], 
                      predicate=edge['predicate'])
    
    # Create layout optimized for 1-hop (star pattern)
    pos = {}
    center_pos = (0, 0)
    pos[center_id] = center_pos
    
    # Arrange 1-hop neighbors in a circle around center
    neighbors = [n for n in G.nodes() if G.nodes[n]['hop'] == 1]
    import math
    for i, neighbor in enumerate(neighbors):
        angle = 2 * math.pi * i / len(neighbors)
        radius = 3
        pos[neighbor] = (radius * math.cos(angle), radius * math.sin(angle))
    
    # Create figure
    plt.figure(figsize=(20, 20))
    
    # Define colors for different categories
    category_colors = {
        'biolink:OrganismTaxon': '#FF6B6B',
        'biolink:ChemicalEntity': '#4ECDC4',
        'biolink:ChemicalMixture': '#45B7D1',
        'biolink:Enzyme': '#96CEB4',
        'biolink:PhenotypicQuality': '#FFEAA7',
        'biolink:EnvironmentalFeature': '#DDA0DD',
        'biolink:ActivityAndBehavior': '#FFB347'
    }
    
    # Draw center node
    center_categories = str(G.nodes[center_id]['category']).split('|') if G.nodes[center_id]['category'] else ['unknown']
    center_color = category_colors.get(center_categories[0], '#CCCCCC')
    
    nx.draw_networkx_nodes(G, pos, nodelist=[center_id], 
                          node_color=[center_color], 
                          node_size=[6000],
                          alpha=0.9,
                          edgecolors='black',
                          linewidths=2)
    
    # Draw 1-hop neighbors
    neighbor_nodes = [node for node, data in G.nodes(data=True) if data.get('hop') == 1]
    neighbor_colors = []
    for node in neighbor_nodes:
        categories = str(G.nodes[node]['category']).split('|') if G.nodes[node]['category'] else ['unknown']
        primary_category = categories[0]
        color = category_colors.get(primary_category, '#CCCCCC')
        neighbor_colors.append(color)
    
    nx.draw_networkx_nodes(G, pos, nodelist=neighbor_nodes, 
                          node_color=neighbor_colors, 
                          node_size=[3000 for _ in neighbor_nodes],
                          alpha=0.8,
                          edgecolors='black',
                          linewidths=1.5)
    
    # Draw edges
    nx.draw_networkx_edges(G, pos, alpha=0.5, width=2, edge_color='gray')
    
    # Create comprehensive labels for ALL nodes
    labels = {}
    
    # Center node label
    center_name = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    labels[center_id] = center_name
    
    # ALL 1-hop neighbors (since there are fewer, we can label them all)
    for neighbor in neighbor_nodes:
        name = str(G.nodes[neighbor]['name']) if G.nodes[neighbor]['name'] else neighbor
        # Clean up long names
        if len(name) > 30:
            name = name[:30] + "..."
        labels[neighbor] = name
    
    # Draw labels with better formatting
    nx.draw_networkx_labels(G, pos, labels, font_size=10, font_weight='bold', 
                           font_color='black', bbox=dict(boxstyle='round,pad=0.3', 
                           facecolor='white', alpha=0.9, edgecolor='gray'))
    
    # Add title
    center_name_full = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    plt.title(f'1-Hop Subgraph around {center_name_full}\\n({len(G.nodes)} nodes, {len(G.edges)} edges)', 
              fontsize=20, fontweight='bold', pad=40)
    
    # Add legend with better positioning
    legend_elements = []
    for category, color in category_colors.items():
        if any(category in str(data.get('category', '')) for _, data in G.nodes(data=True)):
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=color, markersize=12, 
                                            label=category.replace('biolink:', '')))
    
    # Add hop legend
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=18, 
                                    label='Center (Hop 0)'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=12, 
                                    label='1-Hop Neighbors'))
    
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
              fontsize=12, frameon=True, fancybox=True, shadow=True)
    
    # Remove axes
    plt.axis('off')
    
    # Adjust layout and save
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()
    
    print(f"1-hop visualization saved to {output_file}")

def main():
    # File paths
    nodes_file = "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/merged/20250222/merged-kg_nodes.tsv"
    edges_file = "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/data/merged/20250222/merged-kg_edges.tsv"
    
    # Load data
    nodes_df, edges_df = load_data(nodes_file, edges_file)
    
    # Find 1-hop subgraph around Corynebacterium glutamicum
    center_id = "NCBITaxon:1718"
    subgraph_nodes, subgraph_edges = find_1hop_subgraph(nodes_df, edges_df, center_id)
    
    if subgraph_nodes is None:
        return
    
    # Export subgraph data
    output_prefix = "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe/neo4j/corynebacterium_glutamicum_1hop"
    
    subgraph_nodes.to_csv(f"{output_prefix}_subgraph_nodes.csv", index=False)
    subgraph_edges.to_csv(f"{output_prefix}_subgraph_edges.csv", index=False)
    
    # Create visualization
    visualization_file = f"{output_prefix}_subgraph.png"
    create_1hop_visualization(subgraph_nodes, subgraph_edges, center_id, visualization_file)
    
    # Print summary
    print("\\n1-Hop Subgraph Summary:")
    print(f"Center node: {center_id}")
    center_name = subgraph_nodes[subgraph_nodes['id'] == center_id]['name'].iloc[0]
    print(f"Center name: {center_name}")
    print(f"Total nodes: {len(subgraph_nodes)}")
    print(f"Total edges: {len(subgraph_edges)}")
    
    # Print nodes by hop
    for hop in [0, 1]:
        hop_count = len(subgraph_nodes[subgraph_nodes['hop'] == hop])
        print(f"Hop {hop} nodes: {hop_count}")
    
    # Print top categories
    print("\\nTop node categories:")
    categories = subgraph_nodes['category'].value_counts().head(10)
    for category, count in categories.items():
        print(f"  {category}: {count}")
    
    # Export summary stats
    stats = {
        'center_id': center_id,
        'center_name': center_name,
        'total_nodes': len(subgraph_nodes),
        'total_edges': len(subgraph_edges),
        'hop_0_nodes': len(subgraph_nodes[subgraph_nodes['hop'] == 0]),
        'hop_1_nodes': len(subgraph_nodes[subgraph_nodes['hop'] == 1]),
        'top_categories': categories.to_dict()
    }
    
    with open(f"{output_prefix}_stats.json", 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"\\nFiles created:")
    print(f"- {output_prefix}_subgraph_nodes.csv")
    print(f"- {output_prefix}_subgraph_edges.csv")
    print(f"- {output_prefix}_subgraph.png")
    print(f"- {output_prefix}_stats.json")

if __name__ == "__main__":
    main()