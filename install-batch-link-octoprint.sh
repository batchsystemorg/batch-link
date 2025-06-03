#!/bin/bash

copy_files() {
    local passed_uuid=$1

    echo -e "\033[0m "
    read -p "Rasp Pi IP address: " ip_address
    read -p "The username pls: " username

    # ssh $username@$ip_address "mkdir -p /home/$username/batch-link"
    echo -e "And the password ⊂(◉‿◉)つ"
    scp -pr batch-link/* $username@$ip_address:/home/$username/batch-link
    echo 'Files copied to Pi'

    echo -e "\033[95m "
    echo " __i"
    echo "|---|    "
    echo "|[_]|    "
    echo "|:::|    "
    echo "|:::|    "
    echo "'\   \   "
    echo "  \_=_\ dialing in now"
    echo " "
    echo -e "\033[0m "

    ssh -t $username@$ip_address "\
      echo 'Connected to Raspberry Pi.'; \
      cd /home/$username/batch-link; \
      echo 'Initiate install script on Pi'; \
      bash install-on-pi-octoprint.sh ${passed_uuid};"

}

main() {
    echo -e "\033[32m"
    echo "                                                    
                                                                                                      
                                                                                          
                                                                                          
                                                                                          
                                                                                          
                                            ..                                            
                                      ..:::::::::::.                                      
                                                                                          
                            .:::------==============------:::.                            
                                                                                          
                        ::---===++++*****************+++++===---::                        
                                                                                          
                     ::::-----======+++++++++++++++++++=====-----::::                     
                           .....:::::::------------:::::::.....                           
                    .....::::-----======++++++++++======-----::::.....                    
                   ..:::::----====++++++++******++++++++====----:::::..                   
                           ....::::-------------------:::::....                           
                  ::--===++++*****######################*****++++===--::                  
                                .....::::--------::::.....                                
                 ::--==++**####################################**++==--::                 
                               ....::::::--------::::::....                               
                  ::---====++++****####################****++++====---::                  
                         ....:::::------=========-------::::.....                         
                   ...::::-----====+++++++++++++++++++=====-----::::...                   
                    ....:::::----======++++++++++++======----:::::....                    
                             .....::::::::::::::::::::::.....                             
                     ::-----======+++++++++****++++++++++=====-----::                     
                                                                                          
                        ::---===++++******************+++====---::                        
                                                                                          
                             :::-------=============-----::::.                            
                                                                                          
                                      ..::::::::::..                                      
                                            ..                                            
                                                                                          
                                                                                          
                                BATCH LINK OCTOPRINT INSTALLER                                                     
                                                                                          
                                                                                          
                                                                                      
            "
    echo -e "\033[32m"
    read -p "You got Octoprint on your Pi? (Y/N): " copy_option
    if [[ $copy_option == "Y" || $copy_option == "y" ]]; 
    then
        UUID_ARG="$1"
        copy_files "$UUID_ARG"
    else
        echo "Okey, sorry to hear, see ya next time :)"
    fi
}

main