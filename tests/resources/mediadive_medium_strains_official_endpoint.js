{type:"get",url:"/medium-strains/:id",title:"All strains for one medium",name:"GetMediumStrains",group:"Medium",parameter:{fields:{Parameter:[{group:"Parameter",type:"String",optional:!1,field:"id",description:"<p>Medium unique ID. Might start with collection prefix.</p>"}]}},sampleRequest:[{url:"https://mediadive.dsmz.de/rest/medium-strains/:id"}],error:{fields:{"Error 404":[{group:"error404",optional:!1,field:"DataNotFound",description:"<p>The medium could not be found or has no calculated composition</p>"}]}},success:{fields:{"Success 200":[{group:"Success 200",type:"String",optional:!1,field:"id",description:"<p>Unique ID of the strain.</p>"},{group:"Success 200",type:"String",optional:!1,field:"species",description:"<p>Species name of the strain</p>"},{group:"Success 200",type:"String",optional:!1,field:"ccno",description:"<p>Unique culture collection number of this strain</p>"},{group:"Success 200",type:"Boolean",optional:!1,field:"growth",description:"<p>True if growth is observed</p>"},{group:"Success 200",type:"Integer",optional:!1,field:"bacdive_id",description:"<p>BacDive-ID is available</p>"},{group:"Success 200",type:"String",optional:!1,field:"domain",description:"<p>Abbreviation for the taxonomic group (B: Bacterium, A:Archaeon, Y: Yeast, F: Fungus, PH: Phage)</p>"}]},examples:[{title:"Example data:",content:`[
    {   
        "id": 1,
        "species": "Weizmannia coagulans",
        "ccno": "DSM 1",
        "growth": 1,
        "bacdive_id": 654,
        "domain": "B"
    },
    ... 
]`,type:"json"}]},version:"0.0.0",filename:"api.php",groupTitle:"Media endpoints",groupDescription:"<p>The following endpoints consider media information. You can request a list of all media, the whole medium recipe containing all solutions, the molecular composition of a medium, or all strains that grow on the medium.</p>"}