#!/usr/bin/env python3
import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np

def create_1hop_full_labels():
    """Create 1-hop visualization with full node labels"""
    
    # Load data
    nodes_df = pd.read_csv('/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_1hop_subgraph_nodes.csv')
    edges_df = pd.read_csv('/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_1hop_subgraph_edges.csv')
    
    center_id = "NCBITaxon:1718"
    
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
    
    # Create layout optimized for 1-hop (star pattern with more space)
    pos = {}
    center_pos = (0, 0)
    pos[center_id] = center_pos
    
    # Arrange 1-hop neighbors in multiple concentric circles if needed
    neighbors = [n for n in G.nodes() if G.nodes[n]['hop'] == 1]
    import math
    
    # Use multiple rings if there are many neighbors
    total_neighbors = len(neighbors)
    if total_neighbors <= 20:
        # Single ring
        radius = 5
        for i, neighbor in enumerate(neighbors):
            angle = 2 * math.pi * i / total_neighbors
            pos[neighbor] = (radius * math.cos(angle), radius * math.sin(angle))
    else:
        # Multiple rings
        neighbors_per_ring = 20
        ring_count = math.ceil(total_neighbors / neighbors_per_ring)
        
        for ring in range(ring_count):
            ring_neighbors = neighbors[ring * neighbors_per_ring:(ring + 1) * neighbors_per_ring]
            radius = 4 + ring * 2.5  # Increasing radius for each ring
            
            for i, neighbor in enumerate(ring_neighbors):
                angle = 2 * math.pi * i / len(ring_neighbors)
                pos[neighbor] = (radius * math.cos(angle), radius * math.sin(angle))
    
    # Create larger figure to accommodate full labels
    plt.figure(figsize=(30, 30))
    
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
                          node_size=[8000],
                          alpha=0.9,
                          edgecolors='black',
                          linewidths=3)
    
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
                          node_size=[4000 for _ in neighbor_nodes],
                          alpha=0.8,
                          edgecolors='black',
                          linewidths=2)
    
    # Draw edges
    nx.draw_networkx_edges(G, pos, alpha=0.3, width=2, edge_color='gray')
    
    # Create FULL labels for ALL nodes - no truncation
    labels = {}
    
    # Center node label
    center_name = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    labels[center_id] = center_name
    
    # ALL 1-hop neighbors with FULL names
    for neighbor in neighbor_nodes:
        name = str(G.nodes[neighbor]['name']) if G.nodes[neighbor]['name'] else neighbor
        # NO TRUNCATION - show full names
        labels[neighbor] = name
    
    # Draw labels with better formatting for readability
    nx.draw_networkx_labels(G, pos, labels, font_size=8, font_weight='bold', 
                           font_color='black', bbox=dict(boxstyle='round,pad=0.4', 
                           facecolor='white', alpha=0.9, edgecolor='gray'))
    
    # Add title
    center_name_full = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    plt.title(f'1-Hop Subgraph around {center_name_full} - FULL LABELS\n({len(G.nodes)} nodes, {len(G.edges)} edges)', 
              fontsize=24, fontweight='bold', pad=50)
    
    # Add legend
    legend_elements = []
    for category, color in category_colors.items():
        if any(category in str(data.get('category', '')) for _, data in G.nodes(data=True)):
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=color, markersize=15, 
                                            label=category.replace('biolink:', '')))
    
    # Add hop legend
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=20, 
                                    label='Center (Hop 0)'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=15, 
                                    label='1-Hop Neighbors'))
    
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
              fontsize=14, frameon=True, fancybox=True, shadow=True)
    
    # Remove axes
    plt.axis('off')
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = '/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_1hop_subgraph_full_labels.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()
    
    print(f"1-hop visualization with full labels saved to {output_file}")

def create_2hop_full_labels():
    """Create 2-hop visualization with full node labels for important nodes"""
    
    # Load data
    nodes_df = pd.read_csv('/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_2hop_subgraph_nodes.csv')
    edges_df = pd.read_csv('/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_2hop_subgraph_edges.csv')
    
    center_id = "NCBITaxon:1718"
    
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
    
    # Create layout with more spacing
    pos = nx.spring_layout(G, k=4, iterations=150, seed=42)
    
    # Create larger figure
    plt.figure(figsize=(35, 30))
    
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

    # Draw nodes by hop
    for hop in [0, 1, 2]:
        hop_nodes = [node for node, data in G.nodes(data=True) if data.get('hop') == hop]
        if not hop_nodes:
            continue
            
        # Get colors for this hop
        node_colors = []
        for node in hop_nodes:
            categories = str(G.nodes[node]['category']).split('|') if G.nodes[node]['category'] else ['unknown']
            primary_category = categories[0]
            color = category_colors.get(primary_category, '#CCCCCC')
            node_colors.append(color)
        
        # Set node size based on hop
        node_sizes = [8000 if hop == 0 else 4000 if hop == 1 else 2000 for _ in hop_nodes]
        
        # Draw nodes
        nx.draw_networkx_nodes(G, pos, nodelist=hop_nodes, 
                              node_color=node_colors, 
                              node_size=node_sizes,
                              alpha=0.8,
                              edgecolors='black',
                              linewidths=2)
    
    # Draw edges
    nx.draw_networkx_edges(G, pos, alpha=0.2, width=1, edge_color='gray')
    
    # Create comprehensive labels with FULL names
    labels = {}
    
    # Center node label (FULL)
    center_name = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    labels[center_id] = center_name
    
    # ALL 1-hop neighbors (FULL names)
    neighbors = list(G.neighbors(center_id))
    for neighbor in neighbors:
        name = str(G.nodes[neighbor]['name']) if G.nodes[neighbor]['name'] else neighbor
        # NO TRUNCATION for 1-hop neighbors
        labels[neighbor] = name
    
    # For 2-hop neighbors, show full names for the most important ones
    hop2_nodes = [node for node, data in G.nodes(data=True) if data.get('hop') == 2]
    # Get degree centrality to identify important 2-hop nodes
    degree_cent = nx.degree_centrality(G)
    important_hop2 = sorted(hop2_nodes, key=lambda x: degree_cent.get(x, 0), reverse=True)[:30]  # Top 30
    
    for node in important_hop2:
        name = str(G.nodes[node]['name']) if G.nodes[node]['name'] else node
        # FULL names for important 2-hop neighbors too
        labels[node] = name
    
    # Draw labels with adjusted formatting for full names
    nx.draw_networkx_labels(G, pos, labels, font_size=7, font_weight='bold', 
                           font_color='black', bbox=dict(boxstyle='round,pad=0.3', 
                           facecolor='white', alpha=0.9, edgecolor='gray'))
    
    # Add title
    center_name_full = str(G.nodes[center_id]['name']) if G.nodes[center_id]['name'] else center_id
    plt.title(f'2-Hop Subgraph around {center_name_full} - FULL LABELS\n({len(G.nodes)} nodes, {len(G.edges)} edges)', 
              fontsize=26, fontweight='bold', pad=60)
    
    # Add legend
    legend_elements = []
    for category, color in category_colors.items():
        if any(category in str(data.get('category', '')) for _, data in G.nodes(data=True)):
            legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                            markerfacecolor=color, markersize=15, 
                                            label=category.replace('biolink:', '')))
    
    # Add hop legend
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=20, 
                                    label='Center (Hop 0)'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=15, 
                                    label='1-Hop Neighbors'))
    legend_elements.append(plt.Line2D([0], [0], marker='o', color='w', 
                                    markerfacecolor='black', markersize=10, 
                                    label='2-Hop Neighbors'))
    
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.02, 1), 
              fontsize=14, frameon=True, fancybox=True, shadow=True)
    
    # Remove axes
    plt.axis('off')
    
    # Adjust layout and save
    plt.tight_layout()
    output_file = '/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/corynebacterium_glutamicum_2hop_subgraph_full_labels.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.show()
    
    print(f"2-hop visualization with full labels saved to {output_file}")

def main():
    print("Creating 1-hop subgraph with full labels...")
    create_1hop_full_labels()
    
    print("\nCreating 2-hop subgraph with full labels...")
    create_2hop_full_labels()
    
    print("\nBoth visualizations with full labels have been created!")
    print("Files saved to: /Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/MicroGrowLink/evaluation_results/")

if __name__ == "__main__":
    main()