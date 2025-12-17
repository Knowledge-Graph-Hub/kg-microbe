#!/usr/bin/env python3
import os
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt

def create_2hop_full_labels():
    """Create 2-hop visualization with full labels for 1-hop neighbors"""

    # Get script directory for relative paths
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Load data
    nodes_df = pd.read_csv(os.path.join(script_dir, 'corynebacterium_glutamicum_2hop_subgraph_nodes.csv'))
    edges_df = pd.read_csv(os.path.join(script_dir, 'corynebacterium_glutamicum_2hop_subgraph_edges.csv'))
    
    center_id = "NCBITaxon:1718"
    
    # Create NetworkX graph
    G = nx.Graph()
    
    # Add nodes
    for _, node in nodes_df.iterrows():
        G.add_node(node['id'], 
                  name=node['name'], 
                  category=node['category'], 
                  hop=node['hop'])
    
    # Add edges (limit for performance)
    edge_count = 0
    for _, edge in edges_df.iterrows():
        if edge_count > 500:  # Limit edges for better performance
            break
        if edge['subject'] in G.nodes and edge['object'] in G.nodes:
            G.add_edge(edge['subject'], edge['object'])
            edge_count += 1
    
    # Create layout with good spacing
    pos = nx.spring_layout(G, k=5, iterations=100, seed=42)
    
    # Create large figure
    plt.figure(figsize=(35, 30))
    
    # Define colors
    category_colors = {
        'biolink:OrganismTaxon': '#FF6B6B',
        'biolink:ChemicalEntity': '#4ECDC4',
        'biolink:ChemicalMixture': '#45B7D1',
        'METPO:1004005': '#45B7D1',  # growth medium
        'biolink:Enzyme': '#96CEB4',
        'biolink:PhenotypicQuality': '#FFEAA7',
        'biolink:EnvironmentalFeature': '#DDA0DD',
        'biolink:ActivityAndBehavior': '#FFB347'
    }
    
    # Draw nodes by hop
    for hop in [0, 1, 2]:
        hop_nodes = [node for node, data in G.nodes(data=True) if data.get('hop') == hop]
        if not hop_nodes:
            continue
            
        node_colors = []
        for node in hop_nodes:
            categories = str(G.nodes[node]['category']).split('|') if G.nodes[node]['category'] else ['unknown']
            primary_category = categories[0]
            color = category_colors.get(primary_category, '#CCCCCC')
            node_colors.append(color)
        
        node_sizes = [10000 if hop == 0 else 5000 if hop == 1 else 2500 for _ in hop_nodes]
        
        nx.draw_networkx_nodes(G, pos, nodelist=hop_nodes, 
                              node_color=node_colors, 
                              node_size=node_sizes,
                              alpha=0.8,
                              edgecolors='black',
                              linewidths=2)
    
    # Draw edges
    nx.draw_networkx_edges(G, pos, alpha=0.2, width=1, edge_color='gray')
    
    # Create labels with FULL names for 1-hop neighbors
    labels = {}
    
    # Center node label (FULL)
    center_name = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    labels[center_id] = center_name
    
    # ALL 1-hop neighbors with COMPLETE FULL names
    neighbors = list(G.neighbors(center_id))
    for neighbor in neighbors:
        name = str(G.nodes[neighbor]['name']) if G.nodes[neighbor]['name'] else neighbor
        # Show COMPLETE full names for all 1-hop neighbors
        labels[neighbor] = name
    
    # For 2-hop, only show the top 20 most connected ones with shorter names
    hop2_nodes = [node for node, data in G.nodes(data=True) if data.get('hop') == 2]
    degree_cent = nx.degree_centrality(G)
    important_hop2 = sorted(hop2_nodes, key=lambda x: degree_cent.get(x, 0), reverse=True)[:20]
    
    for node in important_hop2:
        name = str(G.nodes[node]['name']) if G.nodes[node]['name'] else node
        # Limit 2-hop names to avoid overcrowding
        if len(name) > 25:
            name = name[:25] + "..."
        labels[node] = name
    
    # Draw labels
    nx.draw_networkx_labels(G, pos, labels, font_size=8, font_weight='bold', 
                           font_color='black', 
                           bbox=dict(boxstyle='round,pad=0.3', 
                           facecolor='white', alpha=0.9, edgecolor='gray'))
    
    # Add title
    plt.title(f'2-Hop Subgraph: {center_name} - FULL 1-HOP LABELS\n({len(G.nodes)} nodes, {len(G.edges)} edges)', 
              fontsize=26, fontweight='bold', pad=60)
    
    # Add legend
    legend_elements = []
    for category, color in category_colors.items():
        if any(category in str(data.get('category', '')) for _, data in G.nodes(data=True)):
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=color, markersize=15, 
                                            label=category.replace('biolink:', '')))
    
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=20, 
                                    label='Center (Hop 0)'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=15, 
                                    label='1-Hop (Full Labels)'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=10, 
                                    label='2-Hop (Top 20)'))
    
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
              fontsize=14, frameon=True, fancybox=True, shadow=True)
    
    plt.axis('off')
    plt.tight_layout()

    output_file = os.path.join(script_dir, 'corynebacterium_glutamicum_2hop_subgraph_full_labels.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()

    print(f"2-hop visualization with full 1-hop labels saved to {output_file}")
    print(f"Labels shown: Center + {len(neighbors)} 1-hop neighbors + {len(important_hop2)} top 2-hop neighbors")

if __name__ == "__main__":
    create_2hop_full_labels()