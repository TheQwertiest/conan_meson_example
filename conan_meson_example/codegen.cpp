#include <iostream>
#include <fstream>
#include <cassert>

int main(int argc, char *argv[])
{
    if (argc < 2)
    {
        return 1;
    }
    assert(argv);
    
    std::ofstream out(argv[1]);
    out << 
    "#include <iostream>\n"
    "int main(int, char*[])\n"
    "{\n"
    "    std::cout << \"Hello World!\" << std::endl;\n"
    "    return 0;\n"
    "}\n";
    out.close();
    
    std::cout << "Generated src file: " << std::string(argv[1]) << "\n";
    
    return 0;
}

